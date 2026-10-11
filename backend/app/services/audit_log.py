"""The audit log: who did what, and when, across the application.

One entry per request that creates, changes or deletes something, and per
read that matters (signing in, listening to a recording, downloading an
export, opening this log or the AI log). An entry says who, in what role,
when, which action, what it was done to and whether it succeeded. It never
holds what was sent: no passwords, no transcript text, no customer details.

Entries are written in the background (see log_writer) and removed after
AUDIT_LOG_RETENTION_DAYS.
"""

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from app.services.log_writer import BackgroundWriter

logger = logging.getLogger(__name__)

_SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class AuditEntry:
    occurred_at: float
    # The endpoint's name, e.g. "create_user".
    action: str
    method: str
    # The route as declared, e.g. /api/v1/calls/{call_id}/hold.
    path: str
    status_code: int
    # None when nobody was signed in (a failed sign-in, a telephony webhook).
    user_id: str | None = None
    # The user's role at the time; "telephony" for the provider's webhooks.
    role: str | None = None
    # What it was done to, from the address: ("call", "<call id>").
    target_type: str | None = None
    target_id: str | None = None
    ip_address: str | None = None
    request_id: str | None = None
    # Ids and the like that the endpoint added; never request content.
    detail: dict[str, Any] | None = None
    # Given by the store.
    entry_id: int | None = None

    @property
    def succeeded(self) -> bool:
        return self.status_code < 400


@dataclass(frozen=True)
class AuditFilter:
    user_id: str | None = None
    action: str | None = None
    succeeded: bool | None = None
    target_id: str | None = None
    occurred_from: float | None = None
    occurred_to: float | None = None

    def matches(self, entry: AuditEntry) -> bool:
        return (
            (self.user_id is None or entry.user_id == self.user_id)
            and (self.action is None or entry.action == self.action)
            and (self.succeeded is None or entry.succeeded == self.succeeded)
            and (self.target_id is None or entry.target_id == self.target_id)
            and (self.occurred_from is None or entry.occurred_at >= self.occurred_from)
            and (self.occurred_to is None or entry.occurred_at < self.occurred_to)
        )


@dataclass(frozen=True)
class AuditPage:
    # Newest first.
    entries: tuple[AuditEntry, ...]
    total: int


class AuditLogRepository(ABC):
    @abstractmethod
    def add_many(self, entries: list[AuditEntry]) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(
        self, filters: AuditFilter, limit: int, offset: int
    ) -> tuple[tuple[AuditEntry, ...], int]:
        """A page of matching entries, newest first, and how many match."""
        raise NotImplementedError

    @abstractmethod
    def actions(self) -> tuple[str, ...]:
        """Every action with an entry, in alphabetical order."""
        raise NotImplementedError

    @abstractmethod
    def delete_before(self, cutoff: float) -> int:
        """Remove the entries from before cutoff. Returns how many."""
        raise NotImplementedError


class InMemoryAuditLogRepository(AuditLogRepository):
    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._next_id = 1

    def add_many(self, entries: list[AuditEntry]) -> None:
        for entry in entries:
            self._entries.append(replace(entry, entry_id=self._next_id))
            self._next_id += 1

    def search(
        self, filters: AuditFilter, limit: int, offset: int
    ) -> tuple[tuple[AuditEntry, ...], int]:
        matching = sorted(
            (e for e in self._entries if filters.matches(e)),
            key=lambda e: (e.occurred_at, e.entry_id),
            reverse=True,
        )
        return tuple(matching[offset : offset + limit]), len(matching)

    def actions(self) -> tuple[str, ...]:
        return tuple(sorted({e.action for e in self._entries}))

    def delete_before(self, cutoff: float) -> int:
        kept = [e for e in self._entries if e.occurred_at >= cutoff]
        removed = len(self._entries) - len(kept)
        self._entries = kept
        return removed


class AuditLog:
    def __init__(
        self,
        repository: AuditLogRepository,
        retention_days: float = 365.0,
        clock: Callable[[], float] = time.time,
        max_pending: int = 10_000,
    ) -> None:
        self._repository = repository
        self._retention_days = retention_days
        self._clock = clock
        self._writer: BackgroundWriter[AuditEntry] = BackgroundWriter(
            repository.add_many, "audit", max_pending=max_pending
        )

    @property
    def retention_days(self) -> float:
        return self._retention_days

    def record(self, entry: AuditEntry) -> None:
        self._writer.put(entry)

    def flush(self, timeout: float = 5.0) -> bool:
        return self._writer.flush(timeout)

    def search(self, filters: AuditFilter, limit: int = 50, offset: int = 0) -> AuditPage:
        entries, total = self._repository.search(filters, limit, offset)
        return AuditPage(entries, total)

    def actions(self) -> tuple[str, ...]:
        return self._repository.actions()

    def purge_expired(self) -> int:
        """Remove the entries older than the retention period."""
        removed = self._repository.delete_before(
            self._clock() - self._retention_days * _SECONDS_PER_DAY
        )
        if removed:
            logger.info("Removed %d expired audit log entries", removed)
        return removed
