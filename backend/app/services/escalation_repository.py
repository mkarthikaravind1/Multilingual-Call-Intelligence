import threading
from abc import ABC, abstractmethod
from collections.abc import Iterable

from app.domain.escalation import Escalation, EscalationStatus


class EscalationRepository(ABC):
    @abstractmethod
    def get(self, call_id: str) -> Escalation | None:
        raise NotImplementedError

    @abstractmethod
    def get_many(self, call_ids: Iterable[str]) -> dict[str, Escalation]:
        raise NotImplementedError

    @abstractmethod
    def save(self, escalation: Escalation) -> None:
        """Insert or update the escalation for escalation.call_id."""
        raise NotImplementedError

    @abstractmethod
    def list_by_status(self, statuses: Iterable[EscalationStatus]) -> tuple[Escalation, ...]:
        raise NotImplementedError


class InMemoryEscalationRepository(EscalationRepository):
    def __init__(self) -> None:
        self._escalations: dict[str, Escalation] = {}
        self._lock = threading.Lock()

    def get(self, call_id: str) -> Escalation | None:
        return self._escalations.get(call_id)

    def get_many(self, call_ids: Iterable[str]) -> dict[str, Escalation]:
        return {
            call_id: self._escalations[call_id]
            for call_id in call_ids
            if call_id in self._escalations
        }

    def save(self, escalation: Escalation) -> None:
        with self._lock:
            self._escalations[escalation.call_id] = escalation

    def list_by_status(self, statuses: Iterable[EscalationStatus]) -> tuple[Escalation, ...]:
        wanted = set(statuses)
        return tuple(e for e in self._escalations.values() if e.status in wanted)
