import threading
from abc import ABC, abstractmethod
from collections.abc import Iterable

from app.domain.emerging_complaint_candidate import (
    EmergingComplaintCandidate,
    EmergingComplaintReviewStatus,
)


class EmergingComplaintRepository(ABC):
    @abstractmethod
    def get(self, candidate_id: str) -> EmergingComplaintCandidate | None:
        raise NotImplementedError

    @abstractmethod
    def save(self, candidate: EmergingComplaintCandidate) -> None:
        """Insert or update the candidate with candidate.candidate_id."""
        raise NotImplementedError

    @abstractmethod
    def list_by_status(
        self, statuses: Iterable[EmergingComplaintReviewStatus]
    ) -> tuple[EmergingComplaintCandidate, ...]:
        raise NotImplementedError


class InMemoryEmergingComplaintRepository(EmergingComplaintRepository):
    def __init__(self) -> None:
        self._candidates: dict[str, EmergingComplaintCandidate] = {}
        self._lock = threading.Lock()

    def get(self, candidate_id: str) -> EmergingComplaintCandidate | None:
        return self._candidates.get(candidate_id)

    def save(self, candidate: EmergingComplaintCandidate) -> None:
        with self._lock:
            self._candidates[candidate.candidate_id] = candidate

    def list_by_status(
        self, statuses: Iterable[EmergingComplaintReviewStatus]
    ) -> tuple[EmergingComplaintCandidate, ...]:
        wanted = set(statuses)
        return tuple(c for c in self._candidates.values() if c.status in wanted)
