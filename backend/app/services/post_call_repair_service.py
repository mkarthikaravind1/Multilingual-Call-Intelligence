"""Finds completed calls whose post-call processing never finished (the
process restarted mid-way, the summary provider failed, ...) and runs it
again with a growing delay between attempts.

Post-call processing is idempotent - a stored summary is never regenerated -
so a retry only fills in what is missing. Retry bookkeeping lives in the
shared live-state store and a lock keeps two instances from sweeping at
the same time.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

from app.domain.conversation import ConversationStatus
from app.domain.post_call_summary import PostCallSummary
from app.observability.metrics import POST_CALL_REPAIRS
from app.services.call_service import CallService
from app.services.live_state_store import LiveStateStore
from app.services.post_call_summary_repository import PostCallSummaryRepository

logger = logging.getLogger(__name__)

_LOCK_NAME = "post_call_repair"
_LOCK_TTL_SECONDS = 15 * 60
_STATE_TTL_SECONDS = 7 * 24 * 60 * 60
_LAST_RUN_KEY = "repair:last_run"
_PAGE_SIZE = 100
NO_SUMMARY_ERROR = "Post-call processing produced no summary; see the server logs."


class CallNotRepairableError(ValueError):
    """The call is still active, so there is nothing to repair yet."""


@dataclass(frozen=True)
class PendingCall:
    call_id: str
    first_seen_at: float
    attempts: int
    last_attempt_at: float | None
    last_error: str | None
    gave_up: bool


@dataclass(frozen=True)
class RepairRun:
    ran_at: float
    scanned: int
    pending: int
    repaired: int
    failed: int
    gave_up: int
    # Why the sweep did not run, e.g. another instance is running it.
    skipped_reason: str | None = None


class PostCallRepairService:
    def __init__(
        self,
        call_service: CallService,
        process_completed_call: Callable[[str], PostCallSummary | None],
        summary_repository: PostCallSummaryRepository,
        store: LiveStateStore,
        min_age_seconds: float = 120.0,
        max_attempts: int = 5,
        scan_limit: int = 500,
        clock: Callable[[], float] = time.time,
        background_interval_seconds: float = 0.0,
    ) -> None:
        # How often the background sweep runs; 0 when it is switched off.
        self.background_interval_seconds = background_interval_seconds
        self._call_service = call_service
        self._process = process_completed_call
        self._summaries = summary_repository
        self._store = store
        self._min_age = min_age_seconds
        self._max_attempts = max_attempts
        self._scan_limit = scan_limit
        self._clock = clock

    @property
    def last_run(self) -> RepairRun | None:
        raw = self._store.get_json(_LAST_RUN_KEY)
        return None if raw is None else RepairRun(**raw)

    def pending(self) -> tuple[PendingCall, ...]:
        """Completed calls with speech but no stored summary, newest first."""
        call_ids, _ = self._unprocessed_calls()
        now = self._clock()
        return tuple(self._pending_call(call_id, self._state(call_id, now)) for call_id in call_ids)

    def run(self) -> RepairRun:
        token = self._store.acquire_lock(_LOCK_NAME, _LOCK_TTL_SECONDS)
        if token is None:
            return RepairRun(
                self._clock(), 0, 0, 0, 0, 0, skipped_reason="Another instance is already running it."
            )
        try:
            return self._run()
        finally:
            self._store.release_lock(_LOCK_NAME, token)

    def retry(self, call_id: str) -> PostCallSummary | None:
        """Retry one call now, regardless of attempts and delays."""
        conversation = self._call_service.get_call(call_id)  # 404 for an unknown call
        if conversation.status is not ConversationStatus.COMPLETED:
            raise CallNotRepairableError(f"Call {call_id!r} is still active.")
        state = self._state(call_id, self._clock())
        state["attempts"] = 0
        return self._attempt(call_id, state)

    def _run(self) -> RepairRun:
        call_ids, scanned = self._unprocessed_calls()
        now = self._clock()
        repaired = failed = gave_up = 0
        for call_id in call_ids:
            state = self._state(call_id, now)
            if state["attempts"] >= self._max_attempts:
                gave_up += 1
                continue
            if not self._due(state, now):
                continue
            if self._attempt(call_id, state) is not None:
                repaired += 1
            else:
                failed += 1
                if state["attempts"] >= self._max_attempts:
                    POST_CALL_REPAIRS.inc("gave_up")
                    logger.error(
                        "Giving up on post-call processing for call %r after %d attempts",
                        call_id,
                        state["attempts"],
                    )

        run = RepairRun(now, scanned, len(call_ids), repaired, failed, gave_up)
        self._store.set_json(_LAST_RUN_KEY, asdict(run))
        if repaired or failed:
            logger.info(
                "Post-call repair: %d repaired, %d failed, %d given up (%d pending)",
                repaired,
                failed,
                gave_up,
                len(call_ids),
            )
        return run

    def _attempt(self, call_id: str, state: dict) -> PostCallSummary | None:
        state["attempts"] += 1
        state["last_attempt_at"] = self._clock()
        try:
            summary = self._process(call_id)
            error = None if summary is not None else NO_SUMMARY_ERROR
        except Exception as exc:
            logger.exception("Post-call repair failed for call %r", call_id)
            summary, error = None, f"{type(exc).__name__}: {exc}"

        if summary is not None:
            POST_CALL_REPAIRS.inc("repaired")
            self._store.delete(_state_key(call_id))
            logger.info("Post-call processing repaired for call %r", call_id)
        else:
            POST_CALL_REPAIRS.inc("failed")
            state["last_error"] = error
            self._store.set_json(_state_key(call_id), state, ttl_seconds=_STATE_TTL_SECONDS)
        return summary

    def _due(self, state: dict, now: float) -> bool:
        """Wait min_age after first noticing the call, then back off
        exponentially between attempts."""
        if now - state["first_seen_at"] < self._min_age:
            return False
        if state["last_attempt_at"] is None:
            return True
        delay = self._min_age * (2 ** max(0, state["attempts"] - 1))
        return now - state["last_attempt_at"] >= delay

    def _state(self, call_id: str, now: float) -> dict:
        state = self._store.get_json(_state_key(call_id))
        if state is None:
            state = {"first_seen_at": now, "attempts": 0, "last_attempt_at": None, "last_error": None}
            self._store.set_json(_state_key(call_id), state, ttl_seconds=_STATE_TTL_SECONDS)
        return state

    def _pending_call(self, call_id: str, state: dict) -> PendingCall:
        return PendingCall(
            call_id=call_id,
            first_seen_at=state["first_seen_at"],
            attempts=state["attempts"],
            last_attempt_at=state["last_attempt_at"],
            last_error=state["last_error"],
            gave_up=state["attempts"] >= self._max_attempts,
        )

    def _unprocessed_calls(self) -> tuple[list[str], int]:
        call_ids: list[str] = []
        scanned = offset = 0
        while scanned < self._scan_limit:
            page = self._call_service.list_calls(min(_PAGE_SIZE, self._scan_limit - scanned), offset)
            if not page:
                break
            offset += len(page)
            scanned += len(page)
            for conversation in page:
                if (
                    conversation.status is ConversationStatus.COMPLETED
                    and conversation.utterance_count > 0
                    and self._summaries.get(conversation.call_id) is None
                ):
                    call_ids.append(conversation.call_id)
        return call_ids, scanned


def _state_key(call_id: str) -> str:
    return f"repair:call:{call_id}"
