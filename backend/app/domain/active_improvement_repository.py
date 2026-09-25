from abc import ABC, abstractmethod

from app.domain.active_improvement import ActiveImprovement, ActiveImprovementStatus
from app.domain.learning_evidence import LearningComponent

class ActiveImprovementRepository(ABC):
    @abstractmethod
    def save(self, improvement: ActiveImprovement) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, improvement_id: str) -> ActiveImprovement | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_candidate_id(self, candidate_id: str) -> ActiveImprovement | None:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> tuple[ActiveImprovement, ...]:
        raise NotImplementedError

    @abstractmethod
    def list_active(self) -> tuple[ActiveImprovement, ...]:
        raise NotImplementedError
    
    @abstractmethod
    def list_active_for_component(self, component: LearningComponent):  # ✅ abstract interface
        raise NotImplementedError


class InMemoryActiveImprovementRepository(ActiveImprovementRepository):
    def __init__(self) -> None:
        self._improvements: dict[str, ActiveImprovement] = {}

    def save(self, improvement: ActiveImprovement) -> None:
        self._improvements[improvement.improvement_id] = improvement

    def get(self, improvement_id: str) -> ActiveImprovement | None:
        return self._improvements.get(improvement_id)

    def get_by_candidate_id(self, candidate_id: str) -> ActiveImprovement | None:
        for improvement in self._improvements.values():
            if improvement.candidate_id == candidate_id:
                return improvement
        return None

    def list_all(self) -> tuple[ActiveImprovement, ...]:
        return tuple(self._improvements.values())

    def list_active(self) -> tuple[ActiveImprovement, ...]:
        return tuple(
            improvement
            for improvement in self._improvements.values()
            if improvement.status is ActiveImprovementStatus.ACTIVE
        )

    def list_active_for_component(
        self, component: LearningComponent
    ) -> tuple[ActiveImprovement, ...]:
        return tuple(
            improvement
            for improvement in self._improvements.values()
            if improvement.status is ActiveImprovementStatus.ACTIVE
            and improvement.component is component
        )