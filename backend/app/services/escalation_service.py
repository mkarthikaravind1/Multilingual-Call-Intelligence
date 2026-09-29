import logging
import threading
import time
from collections.abc import Callable, Iterable

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
        """Active escalations most severe first, then the oldest first so
        nothing waits forever; resolved ones most recently resolved first."""
        if active:
            return tuple(
                sorted(
                    self._repository.list_by_status(ACTIVE_STATUSES),
                    key=lambda e: (-e.level.rank, e.first_detected_at),
                )
            )
        return tuple(
            sorted(
                self._repository.list_by_status((EscalationStatus.RESOLVED,)),
                key=lambda e: e.resolved_at or 0.0,
                reverse=True,
            )
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
