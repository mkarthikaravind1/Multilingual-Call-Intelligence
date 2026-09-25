from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.ai.complaint.provider import ComplaintDetectionProvider, ComplaintDetectionResult
from app.ai.question.provider import QuestionGenerationContext, QuestionSuggestionProvider
from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
)
from app.ai.summary.rule_based_provider import RuleBasedSummaryProvider
from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.composition.services import (
    build_call_service,
    build_conversation_analysis_service,
    build_coverage_repository,
    build_estimation_service,
    build_next_question_service,
)
from app.domain.learning_evidence import EvidenceType, LearningComponent
from app.domain.learning_evidence_repository import InMemoryLearningEvidenceRepository
from app.domain.learning_observation_repository import (
    InMemoryLearningObservationRepository,
)
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource
from app.domain.utterance import SpeakerRole, Utterance
from app.services.call_workflow_service import CallWorkflowService, LearningRecordingError
from app.services.learning_call_integration_service import LearningCallIntegrationService
from app.services.learning_evidence_generation_service import (
    LearningEvidenceGenerationService,
)
from app.services.learning_evidence_service import LearningEvidenceService
from app.services.learning_observation_service import LearningObservationService
from app.services.post_call_summary_service import PostCallSummaryService
import time

from app.domain.user import User, UserRole
from app.security.jwt import create_access_token

CALL_ID = "call-1"
QUESTION = "Could you tell me the expected completion time you were given?"


class FakeComplaints(ComplaintDetectionProvider):
    def detect(self, conversation):
        return [ComplaintDetectionResult("Turnaround Time", 0.9, "The car was late.")]


class FakeSentiment(SentimentAnalysisProvider):
    def analyze(self, conversation):
        return SentimentResult(SentimentLabel.NEGATIVE, 0.9, "Customer reported a delay.")


class FakeQuestions(QuestionSuggestionProvider):
    def generate(self, context: QuestionGenerationContext):
        return QuestionSuggestion(
            question=QUESTION,
            target_category=context.category,
            priority=1,
            reason="Needs follow-up.",
            source=SuggestionSource.RULE_BASED,
        )


def utterance(index: int) -> Utterance:
    return Utterance(
        utterance_id=str(index + 1),
        transcript=f"Customer statement {index + 1}.",
        speaker_role=SpeakerRole.CUSTOMER,
        languages=("en",),
        start_time=index * 5.0,
        end_time=index * 5.0 + 4.0,
    )


@dataclass
class Harness:
    workflow: CallWorkflowService
    observations: InMemoryLearningObservationRepository
    evidence: InMemoryLearningEvidenceRepository


def build_workflow(recorder) -> CallWorkflowService:
    call_service = build_call_service()
    call_service.start_call(CALL_ID)
    return CallWorkflowService(
        call_service,
        build_coverage_repository(),
        build_conversation_analysis_service(FakeComplaints(), FakeSentiment()),
        build_next_question_service(FakeQuestions()),
        build_estimation_service(),
        PostCallSummaryService(RuleBasedSummaryProvider()),
        learning_recorder=recorder,
    )


def build(observation_repository=None) -> Harness:
    observations = observation_repository or InMemoryLearningObservationRepository()
    evidence = InMemoryLearningEvidenceRepository()
    recorder = LearningCallIntegrationService(
        LearningObservationService(observations),
        LearningEvidenceGenerationService(LearningEvidenceService(evidence)),
        clock=lambda: 100.0,
    )
    return Harness(build_workflow(recorder), observations, evidence)


def test_utterance_creates_observations_for_connected_components():
    harness = build()

    harness.workflow.process_utterance(CALL_ID, utterance(0))

    observations = harness.observations.list_all()
    assert {o.component for o in observations} == {
        LearningComponent.COMPLAINT_DETECTION,
        LearningComponent.SENTIMENT_ANALYSIS,
        LearningComponent.NEXT_QUESTION,
    }
    assert {o.call_id for o in observations} == {CALL_ID}
    assert {o.predicted_value for o in observations} == {
        "Turnaround Time",
        "NEGATIVE",
        QUESTION,
    }


def test_evidence_is_ai_prediction_without_fake_human_correction():
    harness = build()

    harness.workflow.process_utterance(CALL_ID, utterance(0))

    evidence = harness.evidence.list_all()
    assert len(evidence) == 3
    assert {e.call_id for e in evidence} == {CALL_ID}
    assert all(e.evidence_type is EvidenceType.AI_PREDICTION for e in evidence)
    assert all(e.expected_value is None for e in evidence)
    assert all(e.human_correction is None for e in evidence)
    assert {e.actual_value for e in evidence} == {"Turnaround Time", "NEGATIVE", QUESTION}
    assert {e.component for e in evidence} == {
        LearningComponent.COMPLAINT_DETECTION,
        LearningComponent.SENTIMENT_ANALYSIS,
        LearningComponent.NEXT_QUESTION,
    }


def test_repeated_processing_does_not_duplicate_records():
    harness = build()

    harness.workflow.process_utterance(CALL_ID, utterance(0))
    harness.workflow.process_utterance(CALL_ID, utterance(1))
    harness.workflow.analyze_call(CALL_ID)

    assert len(harness.observations.list_all()) == 3
    assert len(harness.evidence.list_all()) == 3


def test_learning_does_not_change_analysis_result():
    with_learning = build().workflow.process_utterance(CALL_ID, utterance(0))
    without_learning = build_workflow(None).process_utterance(CALL_ID, utterance(0))

    assert with_learning.sentiment == without_learning.sentiment
    assert with_learning.question_suggestion == without_learning.question_suggestion
    assert [(c.category, c.status) for c in with_learning.coverage.complaints] == [
        (c.category, c.status) for c in without_learning.coverage.complaints
    ]


def test_workflow_still_works_without_recorder():
    result = build_workflow(None).process_utterance(CALL_ID, utterance(0))

    assert result.sentiment.label is SentimentLabel.NEGATIVE


def test_learning_storage_failure_does_not_break_call_workflow():
    class FailingObservationRepository(InMemoryLearningObservationRepository):
        def save(self, observation):
            raise RuntimeError("storage down")

    harness = build(FailingObservationRepository())

    result = harness.workflow.process_utterance(CALL_ID, utterance(0))

    assert result.sentiment.label is SentimentLabel.NEGATIVE
    assert harness.evidence.list_all() == ()


def test_recording_error_from_recorder_is_isolated_but_other_errors_propagate():
    class Recorder:
        def __init__(self, error: Exception) -> None:
            self.error = error

        def record(self, call_id, result):
            raise self.error

    isolated = build_workflow(Recorder(LearningRecordingError("boom")))
    assert isolated.process_utterance(CALL_ID, utterance(0)) is not None

    with pytest.raises(RuntimeError, match="bug"):
        build_workflow(Recorder(RuntimeError("bug"))).process_utterance(
            CALL_ID, utterance(0)
        )


def test_analyze_call_is_read_only():
    harness = build()

    harness.workflow.analyze_call(CALL_ID)

    assert harness.observations.list_all() == ()
    assert harness.evidence.list_all() == ()


def api_client() -> TestClient:
    services = build_api_services(
        FakeComplaints(),
        FakeSentiment(),
        FakeQuestions(),
    )

    app = create_app(services)

    user = User(
        user_id="test-icr",
        email="test-icr@example.com",
        password_hash="test-password-hash",
        role=UserRole.ICR,
        is_active=True,
        created_at=time.time(),
    )

    app.state.services.user_repository.save(user)

    token = create_access_token(user)

    return TestClient(
        app,
        headers={"Authorization": f"Bearer {token}"},
    )

def utterance_payload() -> dict:
    return {
        "utterance_id": "1",
        "transcript": "My car was late.",
        "speaker_role": "CUSTOMER",
        "languages": ["en"],
        "start_time": 0.0,
        "end_time": 4.0,
    }


def test_api_utterance_creates_evidence_and_gets_do_not():
    client = api_client()
    client.post("/api/v1/calls", json={"call_id": CALL_ID})
    assert client.get("/api/v1/learning/evidence").json() == []

    assert client.get(f"/api/v1/calls/{CALL_ID}/analysis").status_code == 200
    assert client.get(f"/api/v1/calls/{CALL_ID}").status_code == 200
    assert client.get("/api/v1/learning/evidence").json() == []

    response = client.post(f"/api/v1/calls/{CALL_ID}/utterances", json=utterance_payload())
    assert response.status_code == 200

    evidence = client.get("/api/v1/learning/evidence").json()
    assert len(evidence) == 3
    assert {e["call_id"] for e in evidence} == {CALL_ID}
    assert all(e["human_correction"] is None for e in evidence)

    client.get(f"/api/v1/calls/{CALL_ID}/analysis")
    client.get(f"/api/v1/calls/{CALL_ID}")
    assert len(client.get("/api/v1/learning/evidence").json()) == 3
    assert client.get("/api/v1/learning/candidates").json() == []