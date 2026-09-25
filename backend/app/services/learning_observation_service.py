from app.domain.learning_evidence import LearningComponent
from app.domain.learning_observation import LearningObservation
from app.domain.learning_observation_repository import LearningObservationRepository


class LearningObservationNotFoundError(Exception):
    def __init__(self, observation_id: str) -> None:
        super().__init__(f"Learning observation not found: {observation_id!r}")
        self.observation_id = observation_id


class DuplicateLearningObservationError(ValueError):
    pass


class LearningObservationService:
    def __init__(self, repository: LearningObservationRepository) -> None:
        self._repository = repository

    def record(
        self,
        observation_id: str,
        call_id: str,
        component: LearningComponent,
        description: str,
        predicted_value: str,
        confidence: float,
        created_at: float,
        entity_id: str | None = None,
    ) -> LearningObservation:
        if self._repository.get(observation_id) is not None:
            raise DuplicateLearningObservationError(
                f"Learning observation already exists: {observation_id!r}"
            )

        observation = LearningObservation(
            observation_id=observation_id,
            call_id=call_id,
            component=component,
            description=description,
            predicted_value=predicted_value,
            confidence=confidence,
            created_at=created_at,
            entity_id=entity_id,
        )
        self._repository.save(observation)
        return observation

    def get(self, observation_id: str) -> LearningObservation:
        observation = self._repository.get(observation_id)
        if observation is None:
            raise LearningObservationNotFoundError(observation_id)
        return observation

    def get_for_call(self, call_id: str) -> tuple[LearningObservation, ...]:
        _require_call_id(call_id)
        return self._repository.get_by_call_id(call_id)

    def list_all(self) -> tuple[LearningObservation, ...]:
        return self._repository.list_all()


def _require_call_id(call_id: str) -> None:
    if not isinstance(call_id, str) or not call_id.strip():
        raise ValueError("call_id must not be empty.")