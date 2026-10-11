"""The AI log: what the AI was asked and what it answered, per call.

One entry per request to the LLM: the call it was for, the task, the model,
the prompt and the answer, how long it took, whether the answer could be
used, and the token counts the provider reported.

The prompts contain what the customer said, so this log is kept for a short
time only (AI_LOG_RETENTION_DAYS), is read by administrators only, and
AI_LOG_MODE decides how much is kept: "full" (prompt and answer text),
"details" (everything but the text) or "off".

Entries are written in the background (see log_writer): the AI's answer
never waits for the database.
"""

import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum

from app.services.log_writer import BackgroundWriter

logger = logging.getLogger(__name__)

_SECONDS_PER_DAY = 86400
# How much of an error message or a reason is kept.
MAX_NOTE_CHARS = 500


class AiLogMode(str, Enum):
    FULL = "full"
    DETAILS = "details"
    OFF = "off"


class AiOutcome(str, Enum):
    # The model answered (and nobody said the answer was unusable).
    ANSWERED = "answered"
    # It answered, but not with what was asked for (unreadable JSON, say).
    UNUSABLE = "unusable"
    # The request itself failed (rate limit, network, ...).
    FAILED = "failed"


@dataclass(frozen=True)
class AiLogEntry:
    entry_id: str
    # None for work that belongs to no single call (theme discovery).
    call_id: str | None
    task: str
    model: str
    started_at: float
    duration_ms: float
    outcome: AiOutcome
    # 2 when the request asked again for an answer that could not be used.
    attempt: int = 1
    # None when the text is not kept (AI_LOG_MODE=details), and in lists.
    prompt: str | None = None
    answer: str | None = None
    prompt_chars: int = 0
    answer_chars: int = 0
    # As the provider counted them; None when it did not say.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    # Why the request failed or the answer could not be used.
    note: str | None = None


@dataclass(frozen=True)
class AiLogFilter:
    call_id: str | None = None
    task: str | None = None
    outcome: AiOutcome | None = None
    started_from: float | None = None
    started_to: float | None = None

    def matches(self, entry: AiLogEntry) -> bool:
        return (
            (self.call_id is None or entry.call_id == self.call_id)
            and (self.task is None or entry.task == self.task)
            and (self.outcome is None or entry.outcome == self.outcome)
            and (self.started_from is None or entry.started_at >= self.started_from)
            and (self.started_to is None or entry.started_at < self.started_to)
        )


@dataclass(frozen=True)
class AiLogTotals:
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # Requests the provider gave no token counts for (failed ones, mostly).
    uncounted: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class AiLogPage:
    # Newest first, without the prompt and answer text.
    entries: tuple[AiLogEntry, ...]
    total: int
    totals: AiLogTotals


@dataclass(frozen=True)
class _OutcomeChange:
    entry_id: str
    outcome: AiOutcome
    note: str | None


class AiLogRepository(ABC):
    @abstractmethod
    def add_many(self, entries: list[AiLogEntry]) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_outcome(self, entry_id: str, outcome: AiOutcome, note: str | None) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, entry_id: str) -> AiLogEntry | None:
        """The entry with its prompt and answer text, when kept."""
        raise NotImplementedError

    @abstractmethod
    def search(
        self, filters: AiLogFilter, limit: int, offset: int
    ) -> tuple[tuple[AiLogEntry, ...], int]:
        """A page of matching entries, newest first, without their text;
        and how many match in all."""
        raise NotImplementedError

    @abstractmethod
    def totals(self, filters: AiLogFilter) -> AiLogTotals:
        raise NotImplementedError

    @abstractmethod
    def tasks(self) -> tuple[str, ...]:
        """Every task with an entry, in alphabetical order."""
        raise NotImplementedError

    @abstractmethod
    def delete_before(self, cutoff: float) -> int:
        """Remove the entries started before cutoff. Returns how many."""
        raise NotImplementedError


class InMemoryAiLogRepository(AiLogRepository):
    def __init__(self) -> None:
        self._entries: dict[str, AiLogEntry] = {}

    def add_many(self, entries: list[AiLogEntry]) -> None:
        for entry in entries:
            self._entries[entry.entry_id] = entry

    def set_outcome(self, entry_id: str, outcome: AiOutcome, note: str | None) -> None:
        entry = self._entries.get(entry_id)
        if entry is not None:
            self._entries[entry_id] = replace(entry, outcome=outcome, note=note)

    def get(self, entry_id: str) -> AiLogEntry | None:
        return self._entries.get(entry_id)

    def search(
        self, filters: AiLogFilter, limit: int, offset: int
    ) -> tuple[tuple[AiLogEntry, ...], int]:
        matching = sorted(
            (e for e in self._entries.values() if filters.matches(e)),
            key=lambda e: (e.started_at, e.entry_id),
            reverse=True,
        )
        page = matching[offset : offset + limit]
        return tuple(replace(e, prompt=None, answer=None) for e in page), len(matching)

    def totals(self, filters: AiLogFilter) -> AiLogTotals:
        matching = [e for e in self._entries.values() if filters.matches(e)]
        return AiLogTotals(
            requests=len(matching),
            prompt_tokens=sum(e.prompt_tokens or 0 for e in matching),
            completion_tokens=sum(e.completion_tokens or 0 for e in matching),
            uncounted=sum(1 for e in matching if e.prompt_tokens is None),
        )

    def tasks(self) -> tuple[str, ...]:
        return tuple(sorted({e.task for e in self._entries.values()}))

    def delete_before(self, cutoff: float) -> int:
        old = [key for key, e in self._entries.items() if e.started_at < cutoff]
        for key in old:
            del self._entries[key]
        return len(old)


def parse_mode(value: str) -> AiLogMode:
    """AI_LOG_MODE as a mode; an unknown value keeps the details only, so a
    typing mistake never stores customer speech nobody asked for."""
    try:
        return AiLogMode((value or "").strip().lower())
    except ValueError:
        logger.warning("Unknown AI_LOG_MODE %r; keeping details only", value)
        return AiLogMode.DETAILS


class AiLog:
    def __init__(
        self,
        repository: AiLogRepository,
        mode: AiLogMode = AiLogMode.FULL,
        retention_days: float = 30.0,
        clock: Callable[[], float] = time.time,
        max_pending: int = 10_000,
    ) -> None:
        self._repository = repository
        self._mode = mode
        self._retention_days = retention_days
        self._clock = clock
        self._writer: BackgroundWriter[AiLogEntry | _OutcomeChange] = BackgroundWriter(
            self._write, "ai", max_pending=max_pending
        )

    @property
    def mode(self) -> AiLogMode:
        return self._mode

    @property
    def retention_days(self) -> float:
        return self._retention_days

    @property
    def enabled(self) -> bool:
        return self._mode is not AiLogMode.OFF

    def record(
        self,
        *,
        call_id: str | None,
        task: str,
        model: str,
        prompt: str,
        answer: str | None,
        started_at: float,
        duration_ms: float,
        outcome: AiOutcome,
        attempt: int = 1,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        note: str | None = None,
    ) -> str | None:
        """Queue one request for the log. Returns its id (to report the
        answer unusable later), or None when nothing is kept."""
        if not self.enabled:
            return None
        keep_text = self._mode is AiLogMode.FULL
        entry = AiLogEntry(
            entry_id=uuid.uuid4().hex,
            call_id=call_id,
            task=task or "other",
            model=model,
            started_at=started_at,
            duration_ms=duration_ms,
            outcome=outcome,
            attempt=attempt,
            prompt=prompt if keep_text else None,
            answer=answer if keep_text else None,
            prompt_chars=len(prompt),
            answer_chars=len(answer or ""),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            note=_shortened(note),
        )
        return entry.entry_id if self._writer.put(entry) else None

    def mark_unusable(self, entry_id: str, reason: str) -> None:
        """The answer in this entry turned out not to be what was asked for."""
        self._writer.put(_OutcomeChange(entry_id, AiOutcome.UNUSABLE, _shortened(reason)))

    def flush(self, timeout: float = 5.0) -> bool:
        return self._writer.flush(timeout)

    def get(self, entry_id: str) -> AiLogEntry | None:
        return self._repository.get(entry_id)

    def search(self, filters: AiLogFilter, limit: int = 50, offset: int = 0) -> AiLogPage:
        entries, total = self._repository.search(filters, limit, offset)
        return AiLogPage(entries, total, self._repository.totals(filters))

    def tasks(self) -> tuple[str, ...]:
        return self._repository.tasks()

    def purge_expired(self) -> int:
        """Remove the entries older than the retention period."""
        removed = self._repository.delete_before(
            self._clock() - self._retention_days * _SECONDS_PER_DAY
        )
        if removed:
            logger.info("Removed %d expired AI log entries", removed)
        return removed

    def _write(self, batch: list[AiLogEntry | _OutcomeChange]) -> None:
        # In the order queued: an entry is stored before its outcome changes.
        pending: list[AiLogEntry] = []
        for item in batch:
            if isinstance(item, AiLogEntry):
                pending.append(item)
                continue
            if pending:
                self._repository.add_many(pending)
                pending = []
            self._repository.set_outcome(item.entry_id, item.outcome, item.note)
        if pending:
            self._repository.add_many(pending)


def _shortened(text: str | None) -> str | None:
    if not text:
        return None
    return text if len(text) <= MAX_NOTE_CHARS else text[:MAX_NOTE_CHARS] + "..."
