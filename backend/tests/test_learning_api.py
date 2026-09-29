import dataclasses
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.ai.complaint.provider import ComplaintDetectionProvider, ComplaintDetectionResult
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
)
from app.api.app_factory import create_app
from app.api.dependencies import ApiServices
from app.api.wiring import build_api_services
from app.composition.learning import build_learning_management_service
from app.composition.services import build_call_service
from app.domain.active_improvement_repository import InMemoryActiveImprovementRepository
from app.domain.improvement_candidate import (
    ImprovementCandidate,
    ImprovementReviewStatus,
    ImprovementSpecification,
    ImprovementType,
)
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource
from app.services.human_review_service import HumanReviewService
from app.services.improvement_application_service import ImprovementApplicationService
from app.services.learning_evidence_service import LearningEvidenceService
from app.services.learning_human_review_service import LearningHumanReviewService
from app.services.learning_management_service import LearningManagementService
from app.services.learning_pattern_discovery_service import (
    LearningPatternDiscoveryService,
)
from app.domain.improvement_candidate_repository import (
    InMemoryImprovementCandidateRepository,
)
from app.domain.learning_evidence import EvidenceType, LearningComponent, LearningEvidence
from app.domain.learning_evidence_repository import InMemoryLearningEvidenceRepository
from fastapi.routing import APIRoute
import time

from app.domain.user import User, UserRole
from app.domain.user_repository import InMemoryUserRepository
from app.security.jwt import create_access_token

BASE = "/api/v1/learning"
DESC = "AI predicted complaint_detection 'Cost' and human corrected it to 'Other'."


def make_candidate(candidate_id: str = "cand-1") -> ImprovementCandidate:
    return ImprovementCandidate(
        candidate_id=candidate_id,
        improvement_type=ImprovementType.COMPLAINT_DETECTION,
        title="Improve complaint detection",
        description="Recurring issue.",
        evidence=("ev-1", "ev-2"),
        occurrence_count=2,
        confidence=0.5,
        status=ImprovementReviewStatus.PENDING_REVIEW,
        created_at=1_700_000_000.0,
    )


def make_evidence(evidence_id: str, description: str = DESC) -> LearningEvidence:
    return LearningEvidence(
        evidence_id=evidence_id,
        call_id="call-1",
        evidence_type=EvidenceType.HUMAN_CORRECTION,
        component=LearningComponent.COMPLAINT_DETECTION,
        description=description,
        expected_value="Other",
        actual_value="Cost",
        human_correction="Other",
        created_at=100.0,
    )


def build(candidates=(), evidence=()):
    candidate_repository = InMemoryImprovementCandidateRepository()
    evidence_repository = InMemoryLearningEvidenceRepository()
    for candidate in candidates:
        candidate_repository.save(candidate)
    for record in evidence:
        evidence_repository.save(record)
    learning = build_learning_management_service(evidence_repository, candidate_repository)
    services = ApiServices(
        call_service=build_call_service(),
        workflow_service=None,  # type: ignore[arg-type]
        learning=learning,
        user_repository=InMemoryUserRepository(),
    )
    app = create_app(services)
    user = User(
        user_id="test-supervisor",
        email="test-supervisor@example.com",
        password_hash="test-password-hash",
        role=UserRole.SUPERVISOR,
        is_active=True,
        created_at=time.time(),
    )

    app.state.services.user_repository.save(user)

    token = create_access_token(user)

    client = TestClient(
        app,
        headers={"Authorization": f"Bearer {token}"},
    )

    return client, candidate_repository, evidence_repository


def test_list_candidates_returns_persisted_candidates():
    client, _, _ = build([make_candidate("c1"), make_candidate("c2")])

    response = client.get(f"{BASE}/candidates")

    assert response.status_code == 200
    assert {c["candidate_id"] for c in response.json()} == {"c1", "c2"}


def test_list_candidates_empty():
    client, _, _ = build()

    assert client.get(f"{BASE}/candidates").json() == []


def test_get_candidate_returns_full_representation():
    client, _, _ = build([make_candidate()])

    body = client.get(f"{BASE}/candidates/cand-1").json()

    assert body == {
        "candidate_id": "cand-1",
        "improvement_type": "complaint_detection",
        "title": "Improve complaint detection",
        "description": "Recurring issue.",
        "evidence": ["ev-1", "ev-2"],
        "occurrence_count": 2,
        "confidence": 0.5,
        "status": "pending_review",
        "created_at": 1_700_000_000.0,
        "reviewed_at": None,
    }


def test_get_unknown_candidate_returns_404():
    client, _, _ = build()

    response = client.get(f"{BASE}/candidates/missing")

    assert response.status_code == 404
    assert "missing" in response.json()["detail"]


@pytest.mark.parametrize(
    "action, expected",
    [("approve", "approved"), ("reject", "rejected")],
)
def test_review_changes_status_and_persists(action, expected):
    client, candidate_repository, _ = build([make_candidate()])

    response = client.post(f"{BASE}/candidates/cand-1/{action}")

    assert response.status_code == 200
    assert response.json()["status"] == expected
    assert response.json()["reviewed_at"] is not None
    stored = candidate_repository.get("cand-1")
    assert stored is not None
    assert stored.status.value == expected
    assert client.get(f"{BASE}/candidates/cand-1").json()["status"] == expected


@pytest.mark.parametrize("first", ["approve", "reject"])
@pytest.mark.parametrize("second", ["approve", "reject"])
def test_second_review_returns_409_and_keeps_first_decision(first, second):
    client, candidate_repository, _ = build([make_candidate()])
    client.post(f"{BASE}/candidates/cand-1/{first}")

    response = client.post(f"{BASE}/candidates/cand-1/{second}")

    assert response.status_code == 409
    assert "Traceback" not in response.text
    stored = candidate_repository.get("cand-1")
    assert stored is not None
    assert stored.status.name == ("APPROVED" if first == "approve" else "REJECTED")


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_review_unknown_candidate_returns_404(action):
    client, _, _ = build()

    assert client.post(f"{BASE}/candidates/missing/{action}").status_code == 404


def test_patterns_are_discovered_from_stored_evidence():
    client, _, _ = build(
        evidence=[make_evidence("e1"), make_evidence("e2"), make_evidence("e3", "Other issue.")]
    )

    body = client.get(f"{BASE}/patterns").json()

    assert len(body) == 1
    assert body[0]["component"] == "complaint_detection"
    assert body[0]["occurrence_count"] == 2
    assert set(body[0]["evidence_ids"]) == {"e1", "e2"}
    assert body[0]["description"]
    assert body[0]["suggested_improvement"]


def test_patterns_empty_without_evidence():
    client, _, _ = build()

    assert client.get(f"{BASE}/patterns").json() == []


def test_evidence_endpoint_returns_stored_evidence():
    client, _, _ = build(evidence=[make_evidence("e1")])

    body = client.get(f"{BASE}/evidence").json()

    assert body == [
        {
            "evidence_id": "e1",
            "call_id": "call-1",
            "evidence_type": "human_correction",
            "component": "complaint_detection",
            "description": DESC,
            "expected_value": "Other",
            "actual_value": "Cost",
            "human_correction": "Other",
            "created_at": 100.0,
        }
    ]


def test_get_endpoints_are_read_only():
    client, candidate_repository, evidence_repository = build(
        [make_candidate()], [make_evidence("e1"), make_evidence("e2")]
    )
    candidates_before = candidate_repository.list_all()
    evidence_before = evidence_repository.list_all()

    for path in ("candidates", "candidates/cand-1", "patterns", "evidence"):
        assert client.get(f"{BASE}/{path}").status_code == 200

    assert candidate_repository.list_all() == candidates_before
    assert evidence_repository.list_all() == evidence_before


def test_responses_use_api_schemas_not_domain_objects():
    from app.api.v1 import learning as router_module
    from app.api.v1.learning_schemas import (
        LearningCandidateResponse,
        LearningEvidenceResponse,
        LearningPatternResponse,
    )

    for schema, record in (
        (LearningCandidateResponse, make_candidate()),
        (LearningEvidenceResponse, make_evidence("e1")),
    ):
        response = schema.model_validate(record)
        assert isinstance(response, BaseModel)
        assert not dataclasses.is_dataclass(response)
    assert issubclass(LearningPatternResponse, BaseModel)
    assert all(
        route.response_model is not None
        for route in router_module.router.routes
        if isinstance(route, APIRoute)
    )

def test_routes_use_injected_services():
    client, candidate_repository, _ = build()
    candidate_repository.save(make_candidate("late"))

    assert client.get(f"{BASE}/candidates/late").status_code == 200


def test_default_wiring_provides_empty_learning_services():
    services = ApiServices(
        call_service=build_call_service(),
        workflow_service=None,  # type: ignore[arg-type]
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

    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

    assert client.get(f"{BASE}/candidates").json() == []


def test_existing_call_routes_remain_available():
    client, _, _ = build()

    response = client.post("/api/v1/calls", json={"call_id": "call-1"})

    assert response.status_code == 201
    assert client.get("/learning/candidates").status_code == 404


# ---- The closed loop, through the real composition root ----

class LoopComplaintProvider(ComplaintDetectionProvider):
    """Always sees 'Turnaround Time'; records the guidance it was given."""

    def __init__(self) -> None:
        self.contexts: list[tuple] = []

    def detect(self, conversation, learning_context=()):
        self.contexts.append(tuple(learning_context))
        return [ComplaintDetectionResult("Turnaround Time", 0.9, "The car was late.")]


class LoopSentimentProvider(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEUTRAL, 0.6, "Calm tone.")


class LoopQuestionProvider(QuestionSuggestionProvider):
    def generate(self, context):
        return QuestionSuggestion(
            question="When was the car promised?",
            target_category=context.category,
            priority=1,
            reason="Clarify the delay.",
            source=SuggestionSource.RULE_BASED,
        )


def _client_for(app, role: UserRole) -> TestClient:
    user = User(
        user_id=f"user-{role.value}",
        email=f"{role.value}@example.com",
        password_hash="test-password-hash",
        role=role,
        is_active=True,
        created_at=time.time(),
    )
    app.state.services.user_repository.save(user)
    return TestClient(app, headers={"Authorization": f"Bearer {create_access_token(user)}"})


@pytest.fixture
def loop():
    complaint_provider = LoopComplaintProvider()
    services = build_api_services(
        complaint_provider, LoopSentimentProvider(), LoopQuestionProvider()
    )
    app = create_app(services)
    return SimpleNamespace(
        supervisor=_client_for(app, UserRole.SUPERVISOR),
        icr=_client_for(app, UserRole.ICR),
        complaint_provider=complaint_provider,
    )


def _call_with_utterance(client: TestClient, call_id: str) -> None:
    assert client.post("/api/v1/calls", json={"call_id": call_id}).status_code == 201
    response = client.post(
        f"/api/v1/calls/{call_id}/utterances",
        json={
            "utterance_id": f"{call_id}-u1",
            "transcript": "Nobody told me the car would be late.",
            "speaker_role": "CUSTOMER",
            "languages": ["en"],
            "start_time": 0.0,
            "end_time": 3.0,
        },
    )
    assert response.status_code == 200


def _observation(client: TestClient, call_id: str, component: str) -> dict:
    body = client.get(f"{BASE}/calls/{call_id}/observations").json()
    return next(o for o in body if o["component"] == component)


def _correct(client: TestClient, call_id: str, value: str = "Communication"):
    observation = _observation(client, call_id, "complaint_detection")
    return client.post(
        f"{BASE}/calls/{call_id}/feedback",
        json={
            "observation_id": observation["observation_id"],
            "feedback_type": "human_correction",
            "corrected_value": value,
        },
    )


def test_call_observations_list_ai_outputs_with_correction_options(loop):
    _call_with_utterance(loop.icr, "call-a")

    body = loop.icr.get(f"{BASE}/calls/call-a/observations").json()

    by_component = {o["component"]: o for o in body}
    assert set(by_component) == {"complaint_detection", "sentiment_analysis", "next_question"}
    complaint = by_component["complaint_detection"]
    assert complaint["predicted_value"] == "Turnaround Time"
    assert complaint["feedback"] is None
    assert "Communication" in complaint["correction_options"]
    assert "No complaint" in complaint["correction_options"]
    assert by_component["sentiment_analysis"]["correction_options"] == [
        "POSITIVE",
        "NEUTRAL",
        "NEGATIVE",
    ]
    assert by_component["next_question"]["correction_options"] == []


def test_observations_for_unknown_call_return_404(loop):
    assert loop.icr.get(f"{BASE}/calls/missing/observations").status_code == 404


def test_feedback_is_stored_attached_to_the_observation_and_becomes_evidence(loop):
    _call_with_utterance(loop.icr, "call-a")

    response = _correct(loop.icr, "call-a")

    assert response.status_code == 201
    body = response.json()
    assert body["corrected_value"] == "Communication"
    assert body["original_value"] == "Turnaround Time"
    assert body["source"] == "icr"
    observation = _observation(loop.icr, "call-a", "complaint_detection")
    assert observation["feedback"]["feedback_id"] == body["feedback_id"]
    corrections = [
        e for e in loop.icr.get(f"{BASE}/evidence").json()
        if e["evidence_type"] == "human_correction"
    ]
    assert len(corrections) == 1
    assert corrections[0]["human_correction"] == "Communication"
    assert corrections[0]["actual_value"] == "Turnaround Time"


def test_supervisor_feedback_is_marked_as_supervisor(loop):
    _call_with_utterance(loop.supervisor, "call-a")

    assert _correct(loop.supervisor, "call-a").json()["source"] == "supervisor"


def test_second_feedback_on_the_same_output_returns_409(loop):
    _call_with_utterance(loop.icr, "call-a")
    _correct(loop.icr, "call-a")

    response = _correct(loop.icr, "call-a", "Cost")

    assert response.status_code == 409


@pytest.mark.parametrize(
    "value, detail",
    [("Turnaround Time", "nothing to correct"), ("Not a category", "must be one of")],
)
def test_invalid_corrections_return_422(loop, value, detail):
    _call_with_utterance(loop.icr, "call-a")

    response = _correct(loop.icr, "call-a", value)

    assert response.status_code == 422
    assert detail in response.json()["detail"]


def test_question_feedback_is_accepted_only_for_questions(loop):
    _call_with_utterance(loop.icr, "call-a")
    question = _observation(loop.icr, "call-a", "next_question")
    complaint = _observation(loop.icr, "call-a", "complaint_detection")

    def rate(observation_id, outcome="not_helpful"):
        return loop.icr.post(
            f"{BASE}/calls/call-a/feedback",
            json={
                "observation_id": observation_id,
                "feedback_type": "question_effectiveness",
                "outcome": outcome,
            },
        )

    assert rate(complaint["observation_id"]).status_code == 422
    assert rate(question["observation_id"], "great").status_code == 422
    assert rate(question["observation_id"]).status_code == 201


def test_feedback_for_an_observation_of_another_call_returns_404(loop):
    _call_with_utterance(loop.icr, "call-a")
    _call_with_utterance(loop.icr, "call-b")
    observation = _observation(loop.icr, "call-a", "complaint_detection")

    response = loop.icr.post(
        f"{BASE}/calls/call-b/feedback",
        json={
            "observation_id": observation["observation_id"],
            "feedback_type": "human_correction",
            "corrected_value": "Communication",
        },
    )

    assert response.status_code == 404


def test_repeated_corrections_generate_a_pending_candidate(loop):
    _call_with_utterance(loop.icr, "call-a")
    _call_with_utterance(loop.icr, "call-b")

    _correct(loop.icr, "call-a")
    assert loop.icr.get(f"{BASE}/candidates").json() == []
    _correct(loop.icr, "call-b")

    (candidate,) = loop.icr.get(f"{BASE}/candidates").json()
    assert candidate["status"] == "pending_review"
    assert candidate["improvement_type"] == "complaint_detection"
    assert candidate["occurrence_count"] == 2
    assert "Communication" in candidate["description"]


def test_approval_activates_the_improvement_and_it_shapes_later_calls(loop):
    _call_with_utterance(loop.icr, "call-a")
    _call_with_utterance(loop.icr, "call-b")
    _correct(loop.icr, "call-a")
    _correct(loop.icr, "call-b")
    (candidate,) = loop.icr.get(f"{BASE}/candidates").json()
    assert all(contexts == () for contexts in loop.complaint_provider.contexts)

    approved = loop.supervisor.post(f"{BASE}/candidates/{candidate['candidate_id']}/approve")

    assert approved.status_code == 200
    (improvement,) = loop.icr.get(f"{BASE}/improvements").json()
    assert improvement["candidate_id"] == candidate["candidate_id"]
    assert improvement["status"] == "active"
    assert improvement["component"] == "complaint_detection"
    assert "Communication" in improvement["guidance"]
    assert improvement["usage_count"] == 0

    _call_with_utterance(loop.icr, "call-c")

    latest = loop.complaint_provider.contexts[-1]
    assert [c.improvement_id for c in latest] == [improvement["improvement_id"]]
    (used,) = loop.icr.get(f"{BASE}/improvements").json()
    assert used["usage_count"] == 1


def test_deactivated_improvements_stop_shaping_calls(loop):
    _call_with_utterance(loop.icr, "call-a")
    _call_with_utterance(loop.icr, "call-b")
    _correct(loop.icr, "call-a")
    _correct(loop.icr, "call-b")
    (candidate,) = loop.icr.get(f"{BASE}/candidates").json()
    loop.supervisor.post(f"{BASE}/candidates/{candidate['candidate_id']}/approve")
    (improvement,) = loop.icr.get(f"{BASE}/improvements").json()
    path = f"{BASE}/improvements/{improvement['improvement_id']}/deactivate"

    assert loop.icr.post(path).status_code == 403
    response = loop.supervisor.post(path)

    assert response.status_code == 200
    assert response.json()["status"] == "inactive"
    assert response.json()["deactivated_at"] is not None
    _call_with_utterance(loop.icr, "call-c")
    assert loop.complaint_provider.contexts[-1] == ()


def test_deactivating_an_unknown_improvement_returns_404(loop):
    response = loop.supervisor.post(f"{BASE}/improvements/missing/deactivate")

    assert response.status_code == 404


def test_rejected_candidates_are_not_activated(loop):
    _call_with_utterance(loop.icr, "call-a")
    _call_with_utterance(loop.icr, "call-b")
    _correct(loop.icr, "call-a")
    _correct(loop.icr, "call-b")
    (candidate,) = loop.icr.get(f"{BASE}/candidates").json()

    loop.supervisor.post(f"{BASE}/candidates/{candidate['candidate_id']}/reject")

    assert loop.icr.get(f"{BASE}/improvements").json() == []


def test_failed_activation_leaves_the_candidate_pending():
    candidate_repository = InMemoryImprovementCandidateRepository()
    specification = ImprovementSpecification(
        component=LearningComponent.COMPLAINT_DETECTION,
        current_behavior="Recurring correction.",
        proposed_behavior="Fix it.",
        reason="Recurred 2 times.",
    )
    candidate = dataclasses.replace(make_candidate(), specification=specification)
    candidate_repository.save(candidate)

    class FailingImprovements(InMemoryActiveImprovementRepository):
        def save(self, improvement):
            raise RuntimeError("database unavailable")

    evidence_service = LearningEvidenceService(InMemoryLearningEvidenceRepository())
    service = LearningManagementService(
        evidence_service,
        LearningPatternDiscoveryService(evidence_service),
        candidate_repository,
        LearningHumanReviewService(HumanReviewService(), candidate_repository),
        application_service=ImprovementApplicationService(FailingImprovements()),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        service.approve("cand-1")

    assert candidate_repository.get("cand-1") == candidate


def test_legacy_candidate_without_specification_is_approved_without_activation():
    client, candidate_repository, _ = build([make_candidate()])

    response = client.post(f"{BASE}/candidates/cand-1/approve")

    assert response.status_code == 200
    assert candidate_repository.get("cand-1").status is ImprovementReviewStatus.APPROVED