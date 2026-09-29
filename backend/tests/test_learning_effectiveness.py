from dataclasses import dataclass

from app.ai.question.provider import (
    QuestionGenerationContext,
    QuestionSuggestionProvider,
)
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.improvement_candidate import ImprovementSpecification
from app.domain.improvement_effectiveness import (
    ImprovementEffectivenessStatus,
)
from app.domain.improvement_usage_repository import (
    InMemoryImprovementUsageRepository,
)
from app.domain.learning_evidence import (
    EvidenceType,
    LearningComponent,
    LearningEvidence,
)
from app.domain.learning_evidence_repository import (
    InMemoryLearningEvidenceRepository,
)
from app.domain.question_suggestion import (
    QuestionSuggestion,
    SuggestionSource,
)
from app.domain.runtime_improvement_context import (
    RuntimeImprovementContext,
)
from app.services.improvement_effectiveness_service import (
    ImprovementEffectivenessService,
)
from app.services.next_question_service import (
    NextQuestionService,
)
from typing import cast
from app.services.runtime_improvement_service import RuntimeImprovementService

@dataclass
class RecordingProvider(QuestionSuggestionProvider):

    def generate(
        self,
        context: QuestionGenerationContext,
    ) -> QuestionSuggestion:

        return QuestionSuggestion(
            question="What was the promised delivery time?",
            target_category="Turnaround Time",
            priority=1,
            reason="Clarify the promised delivery time.",
            source=SuggestionSource.RULE_BASED,
        )


def build_context() -> RuntimeImprovementContext:

    specification = ImprovementSpecification(
        component=LearningComponent.NEXT_QUESTION,
        current_behavior="Ask generic follow-up questions.",
        proposed_behavior="Ask targeted delivery questions.",
        reason="Repeated missed probing opportunities.",
    )

    return RuntimeImprovementContext(
        improvement_id="improvement-1",
        candidate_id="candidate-1",
        component=LearningComponent.NEXT_QUESTION,
        specification=specification,
    )


def build_evidence(
    evidence_id: str,
    call_id: str,
    evidence_type: EvidenceType,
    expected_value: str | None,
    actual_value: str | None,
) -> LearningEvidence:

    return LearningEvidence(
        evidence_id=evidence_id,
        call_id=call_id,
        evidence_type=evidence_type,
        component=LearningComponent.NEXT_QUESTION,
        description="Question outcome evidence.",
        expected_value=expected_value,
        actual_value=actual_value,
        human_correction=None,
        created_at=100.0,
    )


def build_coverage() -> ConversationCoverage:

    coverage = ConversationCoverage(
        call_id="call-1"
    )

    complaint = coverage.add("Turnaround Time")
    complaint.detect()

    return coverage


def build_suggestion() -> QuestionSuggestion:

    return QuestionSuggestion(
        question="What was the promised delivery time?",
        target_category="Turnaround Time",
        priority=1,
        reason="Clarify the promised delivery time.",
        source=SuggestionSource.RULE_BASED,
    )


def test_runtime_usage_is_recorded():

    usage_repository = InMemoryImprovementUsageRepository()
    evidence_repository = InMemoryLearningEvidenceRepository()

    service = ImprovementEffectivenessService(
        usage_repository=usage_repository,
        evidence_repository=evidence_repository,
        clock=lambda: 100.0,
    )

    service.record_runtime_usage(
        call_id="call-1",
        contexts=(build_context(),),
        suggestion=build_suggestion(),
    )

    usages = usage_repository.list_all()

    assert len(usages) == 1
    assert usages[0].improvement_id == "improvement-1"
    assert usages[0].candidate_id == "candidate-1"
    assert usages[0].call_id == "call-1"
    assert usages[0].component is LearningComponent.NEXT_QUESTION
    assert (
        usages[0].output_value
        == "What was the promised delivery time?"
    )


def test_no_evidence_means_not_enough_evidence():

    usage_repository = InMemoryImprovementUsageRepository()
    evidence_repository = InMemoryLearningEvidenceRepository()

    service = ImprovementEffectivenessService(
        usage_repository,
        evidence_repository,
    )

    service.record_runtime_usage(
        "call-1",
        (build_context(),),
        build_suggestion(),
    )

    result = service.evaluate("improvement-1")

    assert result.usage_count == 1
    assert result.evidence_count == 0
    assert (
        result.status
        is ImprovementEffectivenessStatus.NOT_ENOUGH_EVIDENCE
    )


def test_one_relevant_evidence_is_not_enough():

    usage_repository = InMemoryImprovementUsageRepository()
    evidence_repository = InMemoryLearningEvidenceRepository()

    service = ImprovementEffectivenessService(
        usage_repository,
        evidence_repository,
    )

    service.record_runtime_usage(
        "call-1",
        (build_context(),),
        build_suggestion(),
    )

    evidence_repository.save(
        build_evidence(
            evidence_id="evidence-1",
            call_id="call-1",
            evidence_type=EvidenceType.QUESTION_FEEDBACK,
            expected_value="useful",
            actual_value="useful",
        )
    )

    result = service.evaluate("improvement-1")

    assert result.evidence_count == 1
    assert (
        result.status
        is ImprovementEffectivenessStatus.NOT_ENOUGH_EVIDENCE
    )


def test_two_relevant_evidence_records_make_evidence_available():

    usage_repository = InMemoryImprovementUsageRepository()
    evidence_repository = InMemoryLearningEvidenceRepository()

    service = ImprovementEffectivenessService(
        usage_repository,
        evidence_repository,
    )

    service.record_runtime_usage(
        "call-1",
        (build_context(),),
        build_suggestion(),
    )

    evidence_repository.save(
        build_evidence(
            evidence_id="evidence-1",
            call_id="call-1",
            evidence_type=EvidenceType.QUESTION_FEEDBACK,
            expected_value="useful",
            actual_value="useful",
        )
    )

    evidence_repository.save(
        build_evidence(
            evidence_id="evidence-2",
            call_id="call-1",
            evidence_type=EvidenceType.OUTCOME,
            expected_value="accepted",
            actual_value="accepted",
        )
    )

    result = service.evaluate("improvement-1")

    assert result.usage_count == 1
    assert result.evidence_count == 2
    assert (
        result.status
        is ImprovementEffectivenessStatus.EVIDENCE_AVAILABLE
    )

    assert "useful" in result.observed_outcomes
    assert "accepted" in result.observed_outcomes


def test_unrelated_evidence_is_ignored():

    usage_repository = InMemoryImprovementUsageRepository()
    evidence_repository = InMemoryLearningEvidenceRepository()

    service = ImprovementEffectivenessService(
        usage_repository,
        evidence_repository,
    )

    service.record_runtime_usage(
        "call-1",
        (build_context(),),
        build_suggestion(),
    )

    evidence_repository.save(
        build_evidence(
            evidence_id="evidence-1",
            call_id="other-call",
            evidence_type=EvidenceType.OUTCOME,
            expected_value="accepted",
            actual_value="accepted",
        )
    )

    result = service.evaluate("improvement-1")

    assert result.evidence_count == 0
    assert (
        result.status
        is ImprovementEffectivenessStatus.NOT_ENOUGH_EVIDENCE
    )


def test_next_question_records_runtime_usage_when_learning_is_active():

    usage_repository = InMemoryImprovementUsageRepository()
    evidence_repository = InMemoryLearningEvidenceRepository()

    effectiveness_service = ImprovementEffectivenessService(
        usage_repository=usage_repository,
        evidence_repository=evidence_repository,
        clock=lambda: 100.0,
    )

    class RuntimeImprovementServiceStub:

        def get_context_for_component(self, component):
            assert component is LearningComponent.NEXT_QUESTION
            return (build_context(),)

    service = NextQuestionService(
    provider=RecordingProvider(),
    runtime_improvement_service=cast(
        RuntimeImprovementService,
        RuntimeImprovementServiceStub(),
    ),
    improvement_usage_recorder=effectiveness_service,
)

    service.suggest_next_question(
        build_coverage()
    )

    usages = usage_repository.list_all()

    assert len(usages) == 1
    assert usages[0].improvement_id == "improvement-1"


def test_next_question_keeps_working_without_learning():

    service = NextQuestionService(
        provider=RecordingProvider(),
    )

    suggestion = service.suggest_next_question(
        build_coverage()
    )

    assert suggestion is not None
    assert (
        suggestion.question
        == "What was the promised delivery time?"
    )


# ---- Complaint / sentiment improvements ----

def _complaint_context() -> RuntimeImprovementContext:
    return RuntimeImprovementContext(
        improvement_id="improvement-c",
        candidate_id="candidate-c",
        component=LearningComponent.COMPLAINT_DETECTION,
        specification=ImprovementSpecification(
            component=LearningComponent.COMPLAINT_DETECTION,
            current_behavior="Reviewers corrected 'Turnaround Time' to 'Communication'.",
            proposed_behavior="Tell the two apart.",
            reason="Recurred 3 times.",
        ),
    )


def _correction(evidence_id: str, call_id: str, component: LearningComponent) -> LearningEvidence:
    return LearningEvidence(
        evidence_id=evidence_id,
        call_id=call_id,
        evidence_type=EvidenceType.HUMAN_CORRECTION,
        component=component,
        description="AI predicted x and human corrected it to y.",
        expected_value="y",
        actual_value="x",
        human_correction="y",
        created_at=100.0,
    )


def test_component_usage_is_recorded_once_per_call_and_output():
    usage_repository = InMemoryImprovementUsageRepository()
    service = ImprovementEffectivenessService(
        usage_repository, InMemoryLearningEvidenceRepository()
    )
    context = _complaint_context()

    service.record_component_usage("call-1", (context,), "Communication")
    service.record_component_usage("call-1", (context,), "Communication")
    service.record_component_usage("call-2", (context,), "Communication")

    usages = service.get_usage("improvement-c")
    assert len(usages) == 2
    assert {u.component for u in usages} == {LearningComponent.COMPLAINT_DETECTION}
    assert {u.output_value for u in usages} == {"Communication"}


def test_corrections_on_calls_that_used_a_complaint_improvement_count_as_feedback():
    evidence_repository = InMemoryLearningEvidenceRepository()
    service = ImprovementEffectivenessService(
        InMemoryImprovementUsageRepository(), evidence_repository
    )
    service.record_component_usage("call-1", (_complaint_context(),), "Communication")
    service.record_component_usage("call-2", (_complaint_context(),), "Communication")
    evidence_repository.save(_correction("e1", "call-1", LearningComponent.COMPLAINT_DETECTION))
    evidence_repository.save(_correction("e2", "call-2", LearningComponent.COMPLAINT_DETECTION))
    # Other components on the same calls, and other calls, do not count.
    evidence_repository.save(_correction("e3", "call-1", LearningComponent.SENTIMENT_ANALYSIS))
    evidence_repository.save(_correction("e4", "call-9", LearningComponent.COMPLAINT_DETECTION))

    result = service.evaluate("improvement-c")

    assert result.usage_count == 2
    assert result.evidence_count == 2
    assert result.status is ImprovementEffectivenessStatus.EVIDENCE_AVAILABLE