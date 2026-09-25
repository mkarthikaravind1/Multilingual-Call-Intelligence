import hashlib
import time
from collections.abc import Callable

from app.domain.improvement_effectiveness import (
    ImprovementEffectivenessResult,
    ImprovementEffectivenessStatus,
)
from app.domain.improvement_usage import ImprovementUsage
from app.domain.improvement_usage_repository import (
    ImprovementUsageRepository,
)
from app.domain.learning_evidence import (
    EvidenceType,
    LearningComponent,
    LearningEvidence,
)
from app.domain.learning_evidence_repository import (
    LearningEvidenceRepository,
)
from app.domain.question_suggestion import QuestionSuggestion
from app.domain.runtime_improvement_context import RuntimeImprovementContext


class ImprovementUsageRecordingError(Exception):
    pass


class ImprovementEffectivenessService:

    MIN_EVIDENCE_FOR_EVALUATION = 2

    def __init__(
        self,
        usage_repository: ImprovementUsageRepository,
        evidence_repository: LearningEvidenceRepository,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._usage_repository = usage_repository
        self._evidence_repository = evidence_repository
        self._clock = clock

    def record_runtime_usage(
        self,
        call_id: str,
        contexts: tuple[RuntimeImprovementContext, ...],
        suggestion: QuestionSuggestion,
    ) -> None:
        try:
            for context in contexts:
                usage_id = self._build_usage_id(
                    context.improvement_id,
                    call_id,
                    suggestion.question,
                )

                usage = ImprovementUsage(
                    usage_id=usage_id,
                    improvement_id=context.improvement_id,
                    candidate_id=context.candidate_id,
                    call_id=call_id,
                    component=context.component,
                    output_value=suggestion.question,
                    used_at=self._clock(),
                )

                self._usage_repository.save(usage)

        except Exception as exc:
            raise ImprovementUsageRecordingError(
                "Failed to record improvement runtime usage."
            ) from exc

    def get_usage(
        self,
        improvement_id: str,
    ) -> tuple[ImprovementUsage, ...]:
        return self._usage_repository.list_for_improvement(
            improvement_id
        )

    def evaluate(
        self,
        improvement_id: str,
    ) -> ImprovementEffectivenessResult:
        usages = self.get_usage(improvement_id)

        call_ids = {
            usage.call_id
            for usage in usages
        }

        evidence = tuple(
            item
            for item in self._evidence_repository.list_all()
            if item.call_id in call_ids
            and item.component is LearningComponent.NEXT_QUESTION
            and item.evidence_type
            in {
                EvidenceType.QUESTION_FEEDBACK,
                EvidenceType.OUTCOME,
            }
        )

        observed_outcomes = tuple(
            value
            for item in evidence
            for value in (
                item.expected_value,
                item.actual_value,
            )
            if value is not None
        )

        if len(evidence) >= self.MIN_EVIDENCE_FOR_EVALUATION:
            status = (
                ImprovementEffectivenessStatus.EVIDENCE_AVAILABLE
            )
        else:
            status = (
                ImprovementEffectivenessStatus.NOT_ENOUGH_EVIDENCE
            )

        return ImprovementEffectivenessResult(
            improvement_id=improvement_id,
            usage_count=len(usages),
            evidence_count=len(evidence),
            status=status,
            observed_outcomes=observed_outcomes,
        )

    @staticmethod
    def _build_usage_id(
        improvement_id: str,
        call_id: str,
        question: str,
    ) -> str:
        raw_value = (
            f"{improvement_id}:{call_id}:{question}"
        )

        digest = hashlib.sha256(
            raw_value.encode("utf-8")
        ).hexdigest()[:16]

        return f"usage-{digest}"