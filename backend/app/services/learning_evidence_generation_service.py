import time
from collections.abc import Callable
from uuid import uuid4

from app.domain.learning_evidence import EvidenceType, LearningEvidence
from app.domain.learning_feedback import FeedbackType, LearningFeedback
from app.domain.learning_observation import LearningObservation
from app.services.learning_evidence_service import LearningEvidenceService

_FEEDBACK_TO_EVIDENCE_TYPE: dict[FeedbackType, EvidenceType] = {
    FeedbackType.HUMAN_CORRECTION: EvidenceType.HUMAN_CORRECTION,
    FeedbackType.QUESTION_EFFECTIVENESS: EvidenceType.QUESTION_FEEDBACK,
    FeedbackType.OUTCOME: EvidenceType.OUTCOME,
}


class LearningEvidenceCallMismatchError(ValueError):
    def __init__(self, observation_call_id: str, feedback_call_id: str) -> None:
        super().__init__(
            f"Feedback call_id {feedback_call_id!r} does not match "
            f"observation call_id {observation_call_id!r}."
        )


class LearningEvidenceGenerationService:
    def __init__(
        self,
        evidence_service: LearningEvidenceService,
        id_factory: Callable[[], str] = lambda: f"evidence-{uuid4()}",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._evidence_service = evidence_service
        self._id_factory = id_factory
        self._clock = clock

    def generate(
        self,
        observation: LearningObservation,
        feedback: LearningFeedback | None = None,
    ) -> LearningEvidence:
        if not isinstance(observation, LearningObservation):
            raise TypeError("observation must be a LearningObservation.")

        if feedback is None:
            return self._record(
                observation,
                EvidenceType.AI_PREDICTION,
                description=self._prediction_description(observation),
            )

        if not isinstance(feedback, LearningFeedback):
            raise TypeError("feedback must be a LearningFeedback or None.")
        self._validate_link(observation, feedback)

        if feedback.feedback_type is FeedbackType.HUMAN_CORRECTION:
            return self._from_correction(observation, feedback)
        return self._from_outcome(observation, feedback)

    @staticmethod
    def _validate_link(
        observation: LearningObservation, feedback: LearningFeedback
    ) -> None:
        if feedback.observation_id != observation.observation_id:
            raise ValueError(
                f"Feedback {feedback.feedback_id!r} references observation "
                f"{feedback.observation_id!r}, not {observation.observation_id!r}."
            )
        if feedback.call_id is not None and feedback.call_id != observation.call_id:
            raise LearningEvidenceCallMismatchError(
                observation.call_id, feedback.call_id
            )

    def _from_correction(
        self, observation: LearningObservation, feedback: LearningFeedback
    ) -> LearningEvidence:
        if feedback.corrected_value is None:
            raise ValueError("HUMAN_CORRECTION feedback requires corrected_value.")
        return self._record(
            observation,
            EvidenceType.HUMAN_CORRECTION,
            description=(
                f"AI predicted {observation.component.value} "
                f"'{observation.predicted_value}' and human corrected it to "
                f"'{feedback.corrected_value}'."
            ),
            expected_value=feedback.corrected_value,
            human_correction=feedback.corrected_value,
        )

    def _from_outcome(
        self, observation: LearningObservation, feedback: LearningFeedback
    ) -> LearningEvidence:
        evidence_type = _FEEDBACK_TO_EVIDENCE_TYPE[feedback.feedback_type]
        result = feedback.outcome if feedback.outcome is not None else feedback.corrected_value
        if result is None:
            raise ValueError(
                f"{feedback.feedback_type.value} feedback requires an outcome."
            )
        return self._record(
            observation,
            evidence_type,
            description=(
                f"{evidence_type.value} for {observation.component.value} "
                f"'{observation.predicted_value}': '{result}'."
            ),
            expected_value=result,
        )

    def _record(
        self,
        observation: LearningObservation,
        evidence_type: EvidenceType,
        description: str,
        expected_value: str | None = None,
        human_correction: str | None = None,
    ) -> LearningEvidence:
        return self._evidence_service.record(
            evidence_id=self._id_factory(),
            call_id=observation.call_id,
            evidence_type=evidence_type,
            component=observation.component,
            description=description,
            expected_value=expected_value,
            actual_value=observation.predicted_value,
            human_correction=human_correction,
            created_at=self._clock(),
        )

    @staticmethod
    def _prediction_description(observation: LearningObservation) -> str:
        return (
            f"AI predicted {observation.component.value} "
            f"'{observation.predicted_value}'."
        )