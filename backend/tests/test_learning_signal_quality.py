from app.ai.complaint.provider import ComplaintDetectionProvider, ComplaintDetectionResult
from app.ai.question.provider import QuestionGenerationContext, QuestionSuggestionProvider
from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
)
from app.ai.summary.rule_based_provider import RuleBasedSummaryProvider
from app.composition.learning import build_learning_call_recorder
from app.composition.services import (
    build_call_service,
    build_conversation_analysis_service,
    build_coverage_repository,
    build_estimation_service,
    build_next_question_service,
)
from app.domain.improvement_candidate import ImprovementReviewStatus
from app.domain.learning_evidence import EvidenceType, LearningComponent, LearningEvidence
from app.domain.learning_evidence_repository import InMemoryLearningEvidenceRepository
from app.domain.learning_feedback import FeedbackType, LearningFeedback
from app.domain.learning_observation import LearningObservation
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource
from app.domain.utterance import SpeakerRole, Utterance
from app.services.call_workflow_service import CallWorkflowService
from app.services.human_review_service import HumanReviewService
from app.services.improvement_candidate_service import ImprovementCandidateService
from app.services.learning_candidate_generation_service import (
    LearningCandidateGenerationService,
)
from app.services.learning_evidence_generation_service import (
    LearningEvidenceGenerationService,
)
from app.services.learning_evidence_service import LearningEvidenceService
from app.services.learning_human_review_service import LearningHumanReviewService
from app.services.learning_pattern_discovery_service import (
    LearningPatternDiscoveryService,
)
from app.services.learning_signal_filter_service import LearningSignalFilterService
from app.services.post_call_summary_service import PostCallSummaryService

FILTER = LearningSignalFilterService()


def make_evidence(
    evidence_id: str = "e1",
    evidence_type: EvidenceType = EvidenceType.AI_PREDICTION,
    actual: str | None = "Turnaround Time",
    expected: str | None = None,
    correction: str | None = None,
    description: str = "AI predicted complaint_detection 'Turnaround Time'.",
    component: LearningComponent = LearningComponent.COMPLAINT_DETECTION,
) -> LearningEvidence:
    return LearningEvidence(
        evidence_id=evidence_id,
        call_id=f"call-{evidence_id}",
        evidence_type=evidence_type,
        component=component,
        description=description,
        expected_value=expected,
        actual_value=actual,
        human_correction=correction,
        created_at=100.0,
    )


def discovery_for(*records: LearningEvidence):
    repository = InMemoryLearningEvidenceRepository()
    for record in records:
        repository.save(record)
    evidence_service = LearningEvidenceService(repository)
    return LearningPatternDiscoveryService(evidence_service), repository


def test_prediction_without_expected_value_is_not_a_signal():
    assert FILTER.is_signal(make_evidence()) is False


def test_prediction_with_human_correction_is_a_signal():
    assert FILTER.is_signal(make_evidence(correction="Communication")) is True


def test_prediction_with_different_expected_value_is_a_signal():
    assert FILTER.is_signal(make_evidence(expected="Communication")) is True


def test_prediction_matching_expected_value_is_not_a_signal():
    assert FILTER.is_signal(make_evidence(expected="Turnaround Time")) is False
    assert FILTER.is_signal(make_evidence(expected=" turnaround time ")) is False


def test_explicit_human_correction_evidence_is_a_signal():
    evidence = make_evidence(
        evidence_type=EvidenceType.HUMAN_CORRECTION,
        expected="Communication",
        correction="Communication",
    )

    assert FILTER.is_signal(evidence) is True


def test_correction_equal_to_prediction_is_not_a_signal():
    evidence = make_evidence(
        evidence_type=EvidenceType.HUMAN_CORRECTION,
        expected="Turnaround Time",
        correction="Turnaround Time",
    )

    assert FILTER.is_signal(evidence) is False


def test_outcome_labels_are_not_compared_against_predictions():
    question = make_evidence(
        evidence_type=EvidenceType.QUESTION_FEEDBACK,
        actual="Was the delivery date communicated?",
        expected="useful",
        component=LearningComponent.NEXT_QUESTION,
    )
    outcome = make_evidence(
        evidence_type=EvidenceType.OUTCOME, actual="Oil Change", expected="accepted"
    )

    assert FILTER.is_signal(question) is False
    assert FILTER.is_signal(outcome) is False


def test_repeated_ordinary_predictions_create_no_pattern_or_candidate():
    discovery, repository = discovery_for(
        make_evidence("e1"), make_evidence("e2"), make_evidence("e3")
    )

    patterns = discovery.discover()
    candidates = LearningCandidateGenerationService(
        ImprovementCandidateService()
    ).generate(patterns)

    assert patterns == []
    assert candidates == []
    assert len(repository.list_all()) == 3


def test_repeated_matching_expected_values_create_no_pattern():
    discovery, _ = discovery_for(
        make_evidence("e1", expected="Turnaround Time"),
        make_evidence("e2", expected="Turnaround Time"),
    )

    assert discovery.discover() == []


def test_repeated_corrections_create_pattern_and_candidate():
    description = "AI predicted complaint_detection 'Turnaround Time' and human corrected it to 'Communication'."
    discovery, _ = discovery_for(
        make_evidence(
            "e1",
            evidence_type=EvidenceType.HUMAN_CORRECTION,
            expected="Communication",
            correction="Communication",
            description=description,
        ),
        make_evidence(
            "e2",
            evidence_type=EvidenceType.HUMAN_CORRECTION,
            expected="Communication",
            correction="Communication",
            description=description,
        ),
    )

    patterns = discovery.discover()
    candidates = LearningCandidateGenerationService(
        ImprovementCandidateService()
    ).generate(patterns)

    assert len(patterns) == 1
    assert patterns[0].occurrence_count == 2
    assert set(patterns[0].evidence_ids) == {"e1", "e2"}
    assert len(candidates) == 1
    assert candidates[0].status is ImprovementReviewStatus.PENDING_REVIEW


def test_ordinary_predictions_do_not_dilute_correction_patterns():
    description = "AI predicted complaint_detection 'Cost' and human corrected it to 'Other'."
    discovery, _ = discovery_for(
        make_evidence("p1"),
        make_evidence("p2"),
        make_evidence(
            "c1", EvidenceType.HUMAN_CORRECTION, "Cost", "Other", "Other", description
        ),
        make_evidence(
            "c2", EvidenceType.HUMAN_CORRECTION, "Cost", "Other", "Other", description
        ),
    )

    patterns = discovery.discover()

    assert len(patterns) == 1
    assert set(patterns[0].evidence_ids) == {"c1", "c2"}


def test_generated_correction_evidence_forms_pattern_across_calls():
    repository = InMemoryLearningEvidenceRepository()
    generation = LearningEvidenceGenerationService(
        LearningEvidenceService(repository),
        id_factory=iter(["ev-1", "ev-2"]).__next__,
        clock=lambda: 500.0,
    )
    for index in (1, 2):
        observation = LearningObservation(
            observation_id=f"obs-{index}",
            call_id=f"call-{index}",
            component=LearningComponent.COMPLAINT_DETECTION,
            description="AI output.",
            predicted_value="Turnaround Time",
            confidence=0.9,
            created_at=100.0,
        )
        feedback = LearningFeedback(
            feedback_id=f"fb-{index}",
            observation_id=f"obs-{index}",
            feedback_type=FeedbackType.HUMAN_CORRECTION,
            corrected_value="Communication",
            outcome=None,
            created_at=200.0,
            call_id=f"call-{index}",
        )
        generation.generate(observation, feedback)

    discovery = LearningPatternDiscoveryService(LearningEvidenceService(repository))

    patterns = discovery.discover()

    assert len(patterns) == 1
    assert set(patterns[0].evidence_ids) == {"ev-1", "ev-2"}


class FakeComplaints(ComplaintDetectionProvider):
    def detect(self, conversation):
        return [ComplaintDetectionResult("Turnaround Time", 0.9, "The car was late.")]


class FakeSentiment(SentimentAnalysisProvider):
    def analyze(self, conversation):
        return SentimentResult(SentimentLabel.NEGATIVE, 0.9, "Customer reported a delay.")


class FakeQuestions(QuestionSuggestionProvider):
    def generate(self, context: QuestionGenerationContext):
        return QuestionSuggestion(
            question="When was it promised?",
            target_category=context.category,
            priority=1,
            reason="Needs follow-up.",
            source=SuggestionSource.RULE_BASED,
        )


def test_real_call_predictions_are_stored_but_form_no_patterns():
    call_service = build_call_service()
    repository = InMemoryLearningEvidenceRepository()
    workflow = CallWorkflowService(
        call_service,
        build_coverage_repository(),
        build_conversation_analysis_service(FakeComplaints(), FakeSentiment()),
        build_next_question_service(FakeQuestions()),
        build_estimation_service(),
        PostCallSummaryService(RuleBasedSummaryProvider()),
        learning_recorder=build_learning_call_recorder(repository),
    )
    for call_id in ("call-1", "call-2"):
        call_service.start_call(call_id)
        workflow.process_utterance(
            call_id,
            Utterance(
                utterance_id="1",
                transcript="My car was late.",
                speaker_role=SpeakerRole.CUSTOMER,
                languages=("en",),
                start_time=0.0,
                end_time=4.0,
            ),
        )

    discovery = LearningPatternDiscoveryService(LearningEvidenceService(repository))

    assert len(repository.list_all()) == 6
    assert all(e.evidence_type is EvidenceType.AI_PREDICTION for e in repository.list_all())
    assert discovery.discover() == []


def test_human_review_behaviour_is_unchanged():
    description = "AI predicted complaint_detection 'Cost' and human corrected it to 'Other'."
    discovery, _ = discovery_for(
        make_evidence("c1", EvidenceType.HUMAN_CORRECTION, "Cost", "Other", "Other", description),
        make_evidence("c2", EvidenceType.HUMAN_CORRECTION, "Cost", "Other", "Other", description),
    )
    candidate = LearningCandidateGenerationService(ImprovementCandidateService()).generate(
        discovery.discover()
    )[0]

    approved = LearningHumanReviewService(HumanReviewService()).approve(
        candidate, reviewed_at=candidate.created_at + 1
    )

    assert approved.status is ImprovementReviewStatus.APPROVED
    assert candidate.status is ImprovementReviewStatus.PENDING_REVIEW