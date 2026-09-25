import hashlib
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.learning_evidence import LearningComponent
from app.services.call_workflow_service import CallAnalysisResult, LearningRecordingError
from app.services.learning_evidence_generation_service import (
    LearningEvidenceGenerationService,
)
from app.services.learning_observation_service import (
    DuplicateLearningObservationError,
    LearningObservationService,
)

UNKNOWN_CONFIDENCE = 0.0


@dataclass(frozen=True)
class _Outcome:
    observation_id: str
    component: LearningComponent
    predicted_value: str
    confidence: float
    entity_id: str | None = None


class LearningCallIntegrationService:
    def __init__(
        self,
        observation_service: LearningObservationService,
        generation_service: LearningEvidenceGenerationService,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._observation_service = observation_service
        self._generation_service = generation_service
        self._clock = clock

    def record(self, call_id: str, result: CallAnalysisResult) -> None:
        try:
            for outcome in self._outcomes(call_id, result):
                self._record_outcome(call_id, outcome)
        except Exception as exc:
            raise LearningRecordingError(
                f"Could not record learning data for call {call_id!r}."
            ) from exc

    def _record_outcome(self, call_id: str, outcome: _Outcome) -> None:
        try:
            observation = self._observation_service.record(
                observation_id=outcome.observation_id,
                call_id=call_id,
                component=outcome.component,
                description=f"AI output for {outcome.component.value}.",
                predicted_value=outcome.predicted_value,
                confidence=outcome.confidence,
                created_at=self._clock(),
                entity_id=outcome.entity_id,
            )
        except DuplicateLearningObservationError:
            return
        self._generation_service.generate(observation)

    @staticmethod
    def _outcomes(call_id: str, result: CallAnalysisResult) -> Iterator[_Outcome]:
        for complaint in result.coverage.complaints:
            if complaint.status is ComplaintCoverageStatus.NOT_RAISED:
                continue
            yield _Outcome(
                f"{call_id}:{LearningComponent.COMPLAINT_DETECTION.value}:{complaint.category}",
                LearningComponent.COMPLAINT_DETECTION,
                complaint.category,
                UNKNOWN_CONFIDENCE,
                complaint.category,
            )

        sentiment = result.sentiment
        yield _Outcome(
            f"{call_id}:{LearningComponent.SENTIMENT_ANALYSIS.value}:{sentiment.label.value}",
            LearningComponent.SENTIMENT_ANALYSIS,
            sentiment.label.value,
            sentiment.confidence,
        )

        suggestion = result.question_suggestion
        if suggestion is not None:
            digest = hashlib.sha256(suggestion.question.encode("utf-8")).hexdigest()[:12]
            yield _Outcome(
                f"{call_id}:{LearningComponent.NEXT_QUESTION.value}:"
                f"{suggestion.target_category}:{digest}",
                LearningComponent.NEXT_QUESTION,
                suggestion.question,
                UNKNOWN_CONFIDENCE if suggestion.confidence is None else suggestion.confidence,
                suggestion.target_category,
            )