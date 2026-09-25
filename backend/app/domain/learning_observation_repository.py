from abc import ABC, abstractmethod

from app.domain.learning_observation import LearningObservation


class LearningObservationRepository(ABC):
    @abstractmethod
    def save(self, observation: LearningObservation) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, observation_id: str) -> LearningObservation | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_call_id(self, call_id: str) -> tuple[LearningObservation, ...]:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> tuple[LearningObservation, ...]:
        raise NotImplementedError


class InMemoryLearningObservationRepository(LearningObservationRepository):
    def __init__(self) -> None:
        self._observations: dict[str, LearningObservation] = {}

    def save(self, observation: LearningObservation) -> None:
        self._observations[observation.observation_id] = observation

    def get(self, observation_id: str) -> LearningObservation | None:
        return self._observations.get(observation_id)

    def get_by_call_id(self, call_id: str) -> tuple[LearningObservation, ...]:
        return tuple(o for o in self._observations.values() if o.call_id == call_id)

    def list_all(self) -> tuple[LearningObservation, ...]:
        return tuple(self._observations.values())