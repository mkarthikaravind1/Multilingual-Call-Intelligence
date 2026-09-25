import dataclasses

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.app_factory import create_app
from app.api.dependencies import ApiServices
from app.composition.learning import build_learning_management_service
from app.composition.services import build_call_service
from app.domain.improvement_candidate import (
    ImprovementCandidate,
    ImprovementReviewStatus,
    ImprovementType,
)
from app.domain.improvement_candidate_repository import (
    InMemoryImprovementCandidateRepository,
)
from app.domain.learning_evidence import EvidenceType, LearningComponent, LearningEvidence
from app.domain.learning_evidence_repository import InMemoryLearningEvidenceRepository
from fastapi.routing import APIRoute
import time

from app.domain.user import User, UserRole
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