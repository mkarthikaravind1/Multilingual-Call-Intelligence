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
    complaint_provider: FakeComplaintProvider | None = None,
) -> TestClient:
    services = build_api_services(
        complaint_provider or FakeComplaintProvider(*responses, error=error),
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


def test_list_calls_is_empty_without_calls():
    client = _client()

    response = client.get(BASE)

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_list_calls_returns_newest_first_with_pagination():
    client = _client()
    for call_id in ["call-a", "call-b", "call-c"]:
        _start_call(client, call_id)
    client.post(f"{BASE}/call-a/utterances", json=_utterance())

    first_page = client.get(BASE, params={"limit": 2, "offset": 0}).json()
    second_page = client.get(BASE, params={"limit": 2, "offset": 2}).json()

    assert [item["call_id"] for item in first_page["items"]] == ["call-c", "call-b"]
    assert [item["call_id"] for item in second_page["items"]] == ["call-a"]
    assert first_page["total"] == second_page["total"] == 3
    assert second_page["items"][0] == {
        "call_id": "call-a",
        "status": "active",
        "start_time": 0.0,
        "end_time": None,
        "utterance_count": 1,
        # The fake sentiment is clearly negative, so the call is on watch.
        "escalation_level": "watch",
        "escalation_status": "open",
        # No caller recorded, no complaints resolved.
        "caller_number": None,
        "customer_name": None,
        "vehicle_registration": None,
        "complaints_resolved_at": None,
    }
    assert first_page["items"][0]["escalation_level"] is None


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}],
)
def test_list_calls_rejects_out_of_range_pagination(params):
    client = _client()

    response = client.get(BASE, params=params)

    assert response.status_code == 422


def test_call_stats_counts_calls_by_status():
    client = _client()
    assert client.get("/api/v1/call-stats").json() == {
        "total": 0,
        "active": 0,
        "completed": 0,
    }

    _start_call(client, "call-a")
    _start_call(client, "call-b")
    client.post(f"{BASE}/call-a/complete", json={"end_time": 10.0})

    response = client.get("/api/v1/call-stats")

    assert response.status_code == 200
    assert response.json() == {"total": 2, "active": 1, "completed": 1}


def test_call_named_stats_is_still_retrievable():
    client = _client()
    _start_call(client, "stats")

    response = client.get(f"{BASE}/stats")

    assert response.status_code == 200
    assert response.json()["call_id"] == "stats"


@pytest.mark.parametrize("path", [BASE, "/api/v1/call-stats"])
def test_call_collection_endpoints_require_authentication(path):
    client = _client()
    client.headers.pop("Authorization")

    response = client.get(path)

    assert response.status_code == 401


def test_complete_call_generates_post_call_summary_visible_in_analysis():
    client = _client([_TURNAROUND])
    _start_call(client)
    client.post(f"{BASE}/{CALL_ID}/utterances", json=_utterance())

    assert client.post(f"{BASE}/{CALL_ID}/complete", json={"end_time": 30.0}).status_code == 200
    body = client.get(f"{BASE}/{CALL_ID}/analysis").json()

    assert body["post_call_summary"]["call_id"] == CALL_ID
    assert body["post_call_summary"]["complaints"][0]["category"] == "Turnaround Time"
    assert body["sentiment"] == body["post_call_summary"]["sentiment"]
    assert body["question_suggestion"] is None


def test_repeated_complete_keeps_original_end_time():
    client = _client()
    _start_call(client)
    client.post(f"{BASE}/{CALL_ID}/complete", json={"end_time": 30.0})

    response = client.post(f"{BASE}/{CALL_ID}/complete", json={"end_time": 99.0})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["end_time"] == 30.0
    assert client.get(f"{BASE}/{CALL_ID}").json()["end_time"] == 30.0


def test_completed_call_analysis_makes_no_provider_calls():
    complaint_provider = FakeComplaintProvider([_TURNAROUND])
    client = _client(complaint_provider=complaint_provider)
    _start_call(client)
    client.post(f"{BASE}/{CALL_ID}/utterances", json=_utterance())
    client.post(f"{BASE}/{CALL_ID}/complete", json={"end_time": 30.0})
    calls_after_completion = complaint_provider._calls

    first = client.get(f"{BASE}/{CALL_ID}/analysis").json()
    second = client.get(f"{BASE}/{CALL_ID}/analysis").json()

    assert complaint_provider._calls == calls_after_completion
    assert first == second


def test_completed_call_without_stored_summary_returns_null_post_call_fields():
    client = _client()
    _start_call(client)
    client.post(f"{BASE}/{CALL_ID}/complete", json={"end_time": 30.0})

    body = client.get(f"{BASE}/{CALL_ID}/analysis").json()

    assert body["post_call_summary"] is None
    assert body["sentiment"] is None
    assert body["service_estimate"] is None
    assert body["question_suggestion"] is None


# ---- Duplicate call_id: an existing call is never reset ----

def test_start_call_with_new_call_id_succeeds_after_another_call():
    client = _client()
    _start_call(client, "call-a")

    response = client.post(BASE, json={"call_id": "call-b"})

    assert response.status_code == 201
    assert response.json()["call_id"] == "call-b"


def test_start_call_with_existing_call_id_is_rejected():
    client = _client()
    _start_call(client)
    client.post(f"{BASE}/{CALL_ID}/utterances", json=_utterance())

    response = client.post(BASE, json={"call_id": CALL_ID, "start_time": 9.0})

    assert response.status_code == 409
    assert CALL_ID in response.json()["detail"]
    call = client.get(f"{BASE}/{CALL_ID}").json()
    assert call["status"] == "active"
    assert call["start_time"] == 0.0
    assert call["utterance_count"] == 1


def test_duplicate_start_cannot_reset_a_completed_call_or_its_summary():
    client = _client([_TURNAROUND])
    _start_call(client)
    client.post(f"{BASE}/{CALL_ID}/utterances", json=_utterance(0))
    client.post(f"{BASE}/{CALL_ID}/utterances", json=_utterance(1))
    client.post(f"{BASE}/{CALL_ID}/complete", json={"end_time": 30.0})
    call_before = client.get(f"{BASE}/{CALL_ID}").json()
    summary_before = client.get(f"{BASE}/{CALL_ID}/analysis").json()["post_call_summary"]
    assert summary_before is not None

    response = client.post(BASE, json={"call_id": CALL_ID})

    assert response.status_code == 409
    assert client.get(f"{BASE}/{CALL_ID}").json() == call_before
    assert call_before["status"] == "completed"
    assert call_before["utterance_count"] == 2
    analysis = client.get(f"{BASE}/{CALL_ID}/analysis").json()
    assert analysis["post_call_summary"] == summary_before


def test_concurrent_duplicate_starts_create_exactly_one_call():
    import threading

    from app.domain.conversation import ConversationAlreadyExistsError

    client = _client()
    call_service = client.app.state.services.call_service  # type: ignore[attr-defined]
    barrier = threading.Barrier(8)
    outcomes: list[str] = []

    def start() -> None:
        barrier.wait()
        try:
            call_service.start_call("call-race")
            outcomes.append("created")
        except ConversationAlreadyExistsError:
            outcomes.append("rejected")

    threads = [threading.Thread(target=start) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("created") == 1
    assert outcomes.count("rejected") == 7
    assert client.get(f"{BASE}/call-race").json()["status"] == "active"
