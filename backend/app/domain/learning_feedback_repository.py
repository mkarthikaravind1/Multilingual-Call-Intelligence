from abc import ABC, abstractmethod

from app.domain.learning_feedback import LearningFeedback


class LearningFeedbackRepository(ABC):
    @abstractmethod
    def save(self, feedback: LearningFeedback) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, feedback_id: str) -> LearningFeedback | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_observation_id(self, observation_id: str) -> tuple[LearningFeedback, ...]:
        raise NotImplementedError

    @abstractmethod
    def get_by_call_id(self, call_id: str) -> tuple[LearningFeedback, ...]:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> tuple[LearningFeedback, ...]:
        raise NotImplementedError


class InMemoryLearningFeedbackRepository(LearningFeedbackRepository):
    def __init__(self) -> None:
        self._feedback: dict[str, LearningFeedback] = {}

    def save(self, feedback: LearningFeedback) -> None:
        self._feedback[feedback.feedback_id] = feedback

    def get(self, feedback_id: str) -> LearningFeedback | None:
        return self._feedback.get(feedback_id)

    def get_by_observation_id(self, observation_id: str) -> tuple[LearningFeedback, ...]:
        return tuple(f for f in self._feedback.values() if f.observation_id == observation_id)

    def get_by_call_id(self, call_id: str) -> tuple[LearningFeedback, ...]:
        return tuple(f for f in self._feedback.values() if f.call_id == call_id)

    def list_all(self) -> tuple[LearningFeedback, ...]:
        return tuple(self._feedback.values())