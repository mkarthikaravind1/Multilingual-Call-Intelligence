import logging
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.ai.escalation.provider import EscalationContext, EscalationDetectionProvider
from app.ai.sentiment.provider import SentimentResult
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.escalation import (
    Escalation,
    EscalationLevel,
    EscalationStatus,
)
from app.services.escalation_repository import EscalationRepository

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = (EscalationStatus.OPEN, EscalationStatus.ACKNOWLEDGED)

# The queue views supervisors pick from, as the statuses each one lists.
ESCALATION_VIEWS: dict[str, tuple[EscalationStatus, ...]] = {
    "active": ACTIVE_STATUSES,
    "open": (EscalationStatus.OPEN,),
    "acknowledged": (EscalationStatus.ACKNOWLEDGED,),
    "resolved": (EscalationStatus.RESOLVED,),
    "all": tuple(EscalationStatus),
}


@dataclass(frozen=True)
class EscalationCounts:
    """Overall numbers for the escalation queue, whatever is filtered."""

    active: int
    # Active escalations at the critical level.
    critical: int
    # Open: nobody has acknowledged them yet.
    unacknowledged: int


def _in_range(value: float | None, start: float | None, end: float | None) -> bool:
    """From inclusive, to exclusive; with a bound set, a missing value never matches."""
    if start is None and end is None:
        return True
    if value is None:
        return False
    return (start is None or value >= start) and (end is None or value < end)


class EscalationNotFoundError(Exception):
    def __init__(self, call_id: str) -> None:
        super().__init__(f"No escalation for call {call_id!r}.")
        self.call_id = call_id


class EscalationService:
    """Keeps each call's escalation up to date and lets supervisors work the
    queue. Detection runs only when a call gets a new utterance; reads never
    re-run it."""

    def __init__(
        self,
        repository: EscalationRepository,
        provider: EscalationDetectionProvider,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._clock = clock
        # Serialises the read-modify-write of a call's escalation.
        self._lock = threading.Lock()

    def assess(
        self,
        conversation: Conversation,
        coverage: ConversationCoverage,
        sentiment: SentimentResult | None,
    ) -> Escalation | None:
        """Fold the latest detection into the call's escalation. A detector
        failure is logged and never breaks call processing."""
        call_id = conversation.call_id
        try:
            assessment = self._provider.assess(
                EscalationContext(conversation, coverage, sentiment)
            )
        except Exception:
            logger.exception("Escalation detection failed for call %r", call_id)
            return self._repository.get(call_id)

        with self._lock:
            current = self._repository.get(call_id)
            if assessment.level is EscalationLevel.NONE:
                return current
            now = self._clock()
            if current is None:
                updated = Escalation(
                    call_id=call_id,
                    level=assessment.level,
                    signals=assessment.signals,
                    status=EscalationStatus.OPEN,
                    first_detected_at=now,
                    updated_at=now,
                )
            else:
                updated = current.raise_with(assessment, now)
            if updated is not current:
                self._repository.save(updated)
                if current is None or updated.level is not current.level:
                    logger.info("Call %r escalation is now %s", call_id, updated.level.value)
            return updated

    def get(self, call_id: str) -> Escalation | None:
        return self._repository.get(call_id)

    def get_many(self, call_ids: Iterable[str]) -> dict[str, Escalation]:
        return self._repository.get_many(call_ids)

    def list_queue(self, active: bool = True) -> tuple[Escalation, ...]:
        return self.search("active" if active else "resolved")

    def search(
        self,
        view: str = "active",
        detected_from: float | None = None,
        detected_to: float | None = None,
        acknowledged_from: float | None = None,
        acknowledged_to: float | None = None,
    ) -> tuple[Escalation, ...]:
        """The escalations in a view (see ESCALATION_VIEWS) detected and
        acknowledged within the given epoch-second ranges (from inclusive, to
        exclusive). Active ones come first, most severe then oldest so nothing
        waits forever; then resolved ones, most recently resolved first."""
        matching = [
            e
            for e in self._repository.list_by_status(ESCALATION_VIEWS[view])
            if _in_range(e.first_detected_at, detected_from, detected_to)
            and _in_range(e.acknowledged_at, acknowledged_from, acknowledged_to)
        ]
        active = sorted(
            (e for e in matching if e.is_active),
            key=lambda e: (-e.level.rank, e.first_detected_at),
        )
        resolved = sorted(
            (e for e in matching if not e.is_active),
            key=lambda e: e.resolved_at or 0.0,
            reverse=True,
        )
        return tuple(active + resolved)

    def counts(self) -> EscalationCounts:
        active = self._repository.list_by_status(ACTIVE_STATUSES)
        return EscalationCounts(
            active=len(active),
            critical=sum(1 for e in active if e.level is EscalationLevel.CRITICAL),
            unacknowledged=sum(1 for e in active if e.status is EscalationStatus.OPEN),
        )

    def acknowledge(self, call_id: str, by: str) -> Escalation:
        with self._lock:
            escalation = self._require(call_id).acknowledge(by, self._clock())
            self._repository.save(escalation)
            return escalation

    def resolve(self, call_id: str, by: str, note: str | None = None) -> Escalation:
        with self._lock:
            escalation = self._require(call_id).resolve(by, self._clock(), note)
            self._repository.save(escalation)
            return escalation

    def _require(self, call_id: str) -> Escalation:
        escalation = self._repository.get(call_id)
        if escalation is None:
            raise EscalationNotFoundError(call_id)
        return escalation
