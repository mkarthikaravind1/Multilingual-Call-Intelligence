from app.domain.learning_feedback import FeedbackSource, FeedbackType, LearningFeedback
from app.domain.learning_feedback_repository import LearningFeedbackRepository
from app.services.learning_observation_service import LearningObservationService


class LearningFeedbackNotFoundError(Exception):
    def __init__(self, feedback_id: str) -> None:
        super().__init__(f"Learning feedback not found: {feedback_id!r}")
        self.feedback_id = feedback_id


class LearningFeedbackCallMismatchError(ValueError):
    def __init__(self, observation_id: str, expected_call_id: str, actual_call_id: str) -> None:
        super().__init__(
            f"observation {observation_id!r} belongs to call {actual_call_id!r}, "
            f"not call {expected_call_id!r}."
        )


class DuplicateLearningFeedbackError(ValueError):
    pass


class LearningFeedbackService:
    def __init__(
        self,
        repository: LearningFeedbackRepository,
        observation_service: LearningObservationService,
    ) -> None:
        self._repository = repository
        self._observation_service = observation_service

    def record(
        self,
        feedback_id: str,
        call_id: str,
        observation_id: str,
        feedback_type: FeedbackType,
        created_at: float,
        corrected_value: str | None = None,
        outcome: str | None = None,
        original_value: str | None = None,
        source: FeedbackSource = FeedbackSource.ICR,
        notes: str | None = None,
    ) -> LearningFeedback:
        _require_call_id(call_id)

        if self._repository.get(feedback_id) is not None:
            raise DuplicateLearningFeedbackError(
                f"Learning feedback already exists: {feedback_id!r}"
            )

        feedback = LearningFeedback(
            feedback_id=feedback_id,
            observation_id=observation_id,
            feedback_type=feedback_type,
            corrected_value=corrected_value,
            outcome=outcome,
            created_at=created_at,
            call_id=call_id,
            original_value=original_value,
            source=source,
            notes=notes,
        )

        observation = self._observation_service.get(observation_id)
        if observation.call_id != call_id:
            raise LearningFeedbackCallMismatchError(
                observation_id, call_id, observation.call_id
            )

        self._repository.save(feedback)
        return feedback

    def get(self, feedback_id: str) -> LearningFeedback:
        feedback = self._repository.get(feedback_id)
        if feedback is None:
            raise LearningFeedbackNotFoundError(feedback_id)
        return feedback

    def get_for_observation(self, observation_id: str) -> tuple[LearningFeedback, ...]:
        return self._repository.get_by_observation_id(observation_id)

    def get_for_call(self, call_id: str) -> tuple[LearningFeedback, ...]:
        _require_call_id(call_id)
        return self._repository.get_by_call_id(call_id)

    def list_all(self) -> tuple[LearningFeedback, ...]:
        return self._repository.list_all()


def _require_call_id(call_id: str) -> None:
    if not isinstance(call_id, str) or not call_id.strip():
        raise ValueError("call_id must not be empty.")