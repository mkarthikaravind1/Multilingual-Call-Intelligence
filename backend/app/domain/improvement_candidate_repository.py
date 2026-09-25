from abc import ABC, abstractmethod

from app.domain.improvement_candidate import ImprovementCandidate


class ImprovementCandidateRepository(ABC):
    @abstractmethod
    def save(self, candidate: ImprovementCandidate) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, candidate_id: str) -> ImprovementCandidate | None:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> tuple[ImprovementCandidate, ...]:
        raise NotImplementedError


class InMemoryImprovementCandidateRepository(ImprovementCandidateRepository):
    def __init__(self) -> None:
        self._candidates: dict[str, ImprovementCandidate] = {}

    def save(self, candidate: ImprovementCandidate) -> None:
        self._candidates[candidate.candidate_id] = candidate

    def get(self, candidate_id: str) -> ImprovementCandidate | None:
        return self._candidates.get(candidate_id)

    def list_all(self) -> tuple[ImprovementCandidate, ...]:
        return tuple(self._candidates.values())