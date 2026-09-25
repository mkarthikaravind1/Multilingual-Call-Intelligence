import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.complaint.provider import (
    ComplaintDetectionProvider,
    ComplaintDetectionResult,
)
from app.ai.question.provider import (
    QuestionGenerationContext,
    QuestionSuggestionProvider,
)
from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
)
from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.domain.conversation import Conversation
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource
from app.security.jwt import create_access_token
from app.domain.user import *
from tests.test_auth_helpers import authenticate_client

CALL_ID = "call-1"
BASE = "/api/v1/calls"

_TURNAROUND = ComplaintDetectionResult(
    "Turnaround Time", 0.93, "The vehicle was supposed to be ready yesterday."
)
_COMMUNICATION = ComplaintDetectionResult(
    "Communication", 0.87, "The customer said nobody called them."
)
_SENTIMENT = SentimentResult(
    SentimentLabel.NEGATIVE, 0.9, "The customer reported a delayed service."
)


class FakeComplaintProvider(ComplaintDetectionProvider):
    def __init__(
        self,
        *responses: list[ComplaintDetectionResult],
        error: Exception | None = None,
    ) -> None:
        self._responses = responses
        self._error = error
        self._calls = 0

    def detect(self, conversation: Conversation) -> list[ComplaintDetectionResult]:
        self._calls += 1
        if self._error is not None:
            raise self._error
        if not self._responses:
            return []
        return list(self._responses[min(self._calls, len(self._responses)) - 1])


class FakeSentimentProvider(SentimentAnalysisProvider):
    def analyze(self, conversation: Conversation) -> SentimentResult:
        return _SENTIMENT


class FakeQuestionProvider(QuestionSuggestionProvider):
    def generate(self, context: QuestionGenerationContext) -> QuestionSuggestion | None:
        return QuestionSuggestion(
            question=f"Can you tell me more about the {context.category.lower()} issue?",
            target_category=context.category,
            priority=1,
            reason=f"The {context.category} complaint is {context.status.value}.",
            source=SuggestionSource.RULE_BASED,
        )


def _client(
    *responses: list[ComplaintDetectionResult],
    error: Exception | None = None,
    raise_server_exceptions: bool = True,
) -> TestClient:
    services = build_api_services(
        FakeComplaintProvider(*responses, error=error),
        FakeSentimentProvider(),
        FakeQuestionProvider(),
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
        raise_server_exceptions=raise_server_exceptions,
        headers={"Authorization": f"Bearer {token}"},
    )


def _start_call(client: TestClient, call_id: str = CALL_ID) -> None:
    response = client.post(BASE, json={"call_id": call_id})
    assert response.status_code == 201


def _utterance(index: int = 0, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "utterance_id": str(index + 1),
        "transcript": f"Customer statement {index + 1}.",
        "speaker_role": "CUSTOMER",
        "languages": ["en"],
        "start_time": index * 5.0,
        "end_time": index * 5.0 + 4.0,
    }
    payload.update(overrides)
    return payload


def test_start_call():
    client = _client()

    response = client.post(BASE, json={"call_id": CALL_ID, "start_time": 2.5})

    assert response.status_code == 201
    assert response.json() == {
        "call_id": CALL_ID,
        "status": "active",
        "start_time": 2.5,
        "end_time": None,
        "utterance_count": 0,
        "utterances": [],
    }


def test_get_existing_call():
    client = _client()
    _start_call(client)

    response = client.get(f"{BASE}/{CALL_ID}")

    assert response.status_code == 200
    assert response.json()["call_id"] == CALL_ID
    assert response.json()["status"] == "active"


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("get", "/unknown", None),
        ("post", "/unknown/utterances", _utterance()),
        ("get", "/unknown/analysis", None),
        ("post", "/unknown/complete", {"end_time": 10.0}),
    ],
)
def test_unknown_call_returns_404(method, path, body):
    client = _client()

    response = getattr(client, method)(BASE + path, **({"json": body} if body else {}))

    assert response.status_code == 404
    assert "unknown" in response.json()["detail"]


def test_add_utterance_returns_analysis_and_stores_utterance():
    client = _client([_TURNAROUND])
    _start_call(client)

    response = client.post(f"{BASE}/{CALL_ID}/utterances", json=_utterance())

    assert response.status_code == 200
    assert response.json()["call_id"] == CALL_ID
    call = client.get(f"{BASE}/{CALL_ID}").json()
    assert call["utterance_count"] == 1
    assert call["utterances"][0]["transcript"] == "Customer statement 1."
    assert call["utterances"][0]["speaker_role"] == "CUSTOMER"


def test_response_includes_sentiment():
    client = _client()
    _start_call(client)

    body = client.post(f"{BASE}/{CALL_ID}/utterances", json=_utterance()).json()

    assert body["sentiment"] == {
        "label": "NEGATIVE",
        "confidence": 0.9,
        "evidence": "The customer reported a delayed service.",
    }


def test_response_includes_complaint_coverage():
    client = _client([_TURNAROUND, _COMMUNICATION])
    _start_call(client)

    body = client.post(f"{BASE}/{CALL_ID}/utterances", json=_utterance()).json()

    assert body["coverage"] == {
        "call_id": CALL_ID,
        "complaints": [
            {"category": "Turnaround Time", "status": "detected"},
            {"category": "Communication", "status": "detected"},
        ],
    }


def test_response_includes_next_question_suggestion():
    client = _client([_TURNAROUND])
    _start_call(client)

    body = client.post(f"{BASE}/{CALL_ID}/utterances", json=_utterance()).json()

    suggestion = body["question_suggestion"]
    assert suggestion["target_category"] == "Turnaround Time"
    assert suggestion["source"] == "rule_based"
    assert suggestion["priority"] == 1
    assert suggestion["question"]
    assert suggestion["reason"]


def test_suggestion_is_null_when_no_complaint_is_actionable():
    client = _client()
    _start_call(client)

    body = client.post(f"{BASE}/{CALL_ID}/utterances", json=_utterance()).json()

    assert body["question_suggestion"] is None
    assert body["coverage"]["complaints"] == []


def test_coverage_persists_across_utterances():
    client = _client([_TURNAROUND], [_TURNAROUND, _COMMUNICATION])
    _start_call(client)

    client.post(f"{BASE}/{CALL_ID}/utterances", json=_utterance(0))
    body = client.post(f"{BASE}/{CALL_ID}/utterances", json=_utterance(1)).json()

    assert [c["category"] for c in body["coverage"]["complaints"]] == [
        "Turnaround Time",
        "Communication",
    ]
    assert client.get(f"{BASE}/{CALL_ID}").json()["utterance_count"] == 2


def test_get_analysis_returns_analysis_for_existing_call():
    client = _client([_TURNAROUND])
    _start_call(client)
    client.post(f"{BASE}/{CALL_ID}/utterances", json=_utterance())

    response = client.get(f"{BASE}/{CALL_ID}/analysis")

    assert response.status_code == 200
    body = response.json()
    assert body["call_id"] == CALL_ID
    assert body["sentiment"]["label"] == "NEGATIVE"
    assert body["coverage"]["complaints"] == [
        {"category": "Turnaround Time", "status": "detected"}
    ]

def test_complete_call():
    client = _client()
    _start_call(client)
    response = client.post(f"{BASE}/{CALL_ID}/complete", json={"end_time": 30.0})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["end_time"] == 30.0
    assert client.get(f"{BASE}/{CALL_ID}").json()["status"] == "completed"

def test_complete_call_with_end_time_before_start_is_rejected():
    client = _client()
    client.post(BASE, json={"call_id": CALL_ID, "start_time": 10.0})

    response = client.post(f"{BASE}/{CALL_ID}/complete", json={"end_time": 5.0})

    assert response.status_code == 422

@pytest.mark.parametrize(
    "body",
    [
        {},
        {"call_id": ""},
        {"call_id": "   "},
        {"call_id": CALL_ID, "start_time": "soon"},
        {"call_id": CALL_ID, "conversation_id": CALL_ID},
    ],
)
def test_start_call_rejects_invalid_data(body):
    assert _client().post(BASE, json=body).status_code == 422

@pytest.mark.parametrize(
    "overrides",
    [
        {"speaker_role": "MANAGER"},
        {"languages": []},
        {"languages": ["xx"]},
        {"transcript": ""},
        {"transcript": "   "},
        {"confidence": 1.5},
        {"start_time": 10.0, "end_time": 5.0},
        {"extra_field": "not allowed"},
    ],
)
def test_add_utterance_rejects_invalid_data(overrides):
    client = _client()
    _start_call(client)

    response = client.post(
        f"{BASE}/{CALL_ID}/utterances", json=_utterance(**overrides)
    )

    assert response.status_code == 422
    assert client.get(f"{BASE}/{CALL_ID}").json()["utterance_count"] == 0

def test_add_utterance_rejects_missing_field():
    client = _client()
    _start_call(client)
    payload = _utterance()
    del payload["transcript"]

    assert client.post(f"{BASE}/{CALL_ID}/utterances", json=payload).status_code == 422

def test_out_of_order_utterance_is_rejected():
    client = _client()
    _start_call(client)
    client.post(f"{BASE}/{CALL_ID}/utterances", json=_utterance(1))

    response = client.post(f"{BASE}/{CALL_ID}/utterances", json=_utterance(0))

    assert response.status_code == 422

def test_complete_call_rejects_missing_end_time():
    client = _client()
    _start_call(client)

    assert client.post(f"{BASE}/{CALL_ID}/complete", json={}).status_code == 422

def test_routes_are_only_available_under_api_v1():
    client = _client()

    assert client.post("/calls", json={"call_id": CALL_ID}).status_code == 404

def test_unexpected_provider_error_returns_500():
    client = _client(error=RuntimeError("provider failed"), raise_server_exceptions=False)
    _start_call(client)

    response = client.post(f"{BASE}/{CALL_ID}/utterances", json=_utterance())

    assert response.status_code == 500