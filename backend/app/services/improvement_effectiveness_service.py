import hashlib
import time
from collections.abc import Callable

from collections.abc import Collection

from app.domain.improvement_effectiveness import (
    ImprovementEffect,
    ImprovementEffectMeasure,
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


_FEEDBACK_EVIDENCE_TYPES = frozenset(
    {
        EvidenceType.QUESTION_FEEDBACK,
        EvidenceType.OUTCOME,
        EvidenceType.HUMAN_CORRECTION,
    }
)


class ImprovementUsageRecordingError(Exception):
    pass


class ImprovementEffectivenessService:

    MIN_EVIDENCE_FOR_EVALUATION = 2
    # The effect is judged once the AI gave the output on this many
    # calls since the improvement went live...
    MIN_OUTPUTS_AFTER = 5
    # ...and counts as better or worse when the share corrected moved
    # by at least this much.
    MIN_RATE_CHANGE = 0.10

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
        self.record_component_usage(call_id, contexts, suggestion.question)

    def record_component_usage(
        self,
        call_id: str,
        contexts: tuple[RuntimeImprovementContext, ...],
        output_value: str,
    ) -> None:
        """Record that these improvements shaped an output on this call. The
        id is derived from (improvement, call, output), so re-analysing a
        call with the same result does not add duplicate usage."""
        try:
            for context in contexts:
                usage_id = self._build_usage_id(
                    context.improvement_id,
                    call_id,
                    output_value,
                )

                usage = ImprovementUsage(
                    usage_id=usage_id,
                    improvement_id=context.improvement_id,
                    candidate_id=context.candidate_id,
                    call_id=call_id,
                    component=context.component,
                    output_value=output_value,
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
        # Human feedback on the component the improvement shaped, on the
        # calls where it was used. Every usage of one improvement shares
        # its component.
        components = {usage.component for usage in usages}

        evidence = tuple(
            item
            for item in self._evidence_repository.list_judged()
            if item.call_id in call_ids
            and item.component in components
            and item.evidence_type in _FEEDBACK_EVIDENCE_TYPES
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

    def measure_effect(
        self,
        component: LearningComponent,
        evidence_ids: Collection[str],
        activated_at: float,
        deactivated_at: float | None = None,
    ) -> ImprovementEffectMeasure:
        """Whether reviewers correct the output less often since the
        improvement went live. evidence_ids: the corrections it was
        made from, which say which output it is about.

        Only outputs a reviewer looked at can be corrected, so this is a
        signal for a supervisor to weigh, not a measurement of accuracy."""
        sources = (self._evidence_repository.get(evidence_id) for evidence_id in evidence_ids)
        outputs = {
            source.actual_value
            for source in sources
            if source is not None and source.actual_value is not None
        }
        records = self._evidence_repository.list_for_outputs(component, outputs)

        # One output per call; a correction belongs to the time the AI
        # gave the output, not the (later) time it was reviewed.
        given_at: dict[tuple[str, str], float] = {}
        for record in records:
            if record.evidence_type is EvidenceType.AI_PREDICTION:
                key = (record.call_id, record.actual_value or "")
                given_at[key] = min(given_at.get(key, record.created_at), record.created_at)
        corrected: set[tuple[str, str]] = set()
        for record in records:
            if record.evidence_type is EvidenceType.HUMAN_CORRECTION:
                key = (record.call_id, record.actual_value or "")
                given_at.setdefault(key, record.created_at)
                corrected.add(key)

        def live(at: float) -> bool | None:
            if at < activated_at:
                return False
            return True if deactivated_at is None or at < deactivated_at else None

        counts = {False: [0, 0], True: [0, 0]}  # live? -> [outputs, corrections]
        for key, at in given_at.items():
            period = live(at)
            if period is None:
                continue
            counts[period][0] += 1
            counts[period][1] += key in corrected
        (outputs_before, corrections_before), (outputs_after, corrections_after) = (
            counts[False],
            counts[True],
        )

        if outputs_before == 0 or outputs_after < self.MIN_OUTPUTS_AFTER:
            effect = ImprovementEffect.NOT_ENOUGH_DATA
        else:
            change = corrections_after / outputs_after - corrections_before / outputs_before
            if change <= -self.MIN_RATE_CHANGE:
                effect = ImprovementEffect.BETTER
            elif change >= self.MIN_RATE_CHANGE:
                effect = ImprovementEffect.WORSE
            else:
                effect = ImprovementEffect.NO_CHANGE
        return ImprovementEffectMeasure(
            effect, outputs_before, corrections_before, outputs_after, corrections_after
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