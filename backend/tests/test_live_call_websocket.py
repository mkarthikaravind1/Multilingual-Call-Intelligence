import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

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
from app.api.dependencies import ApiServices
from app.api.wiring import build_api_services
from app.domain.conversation import Conversation
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource
from app.domain.utterance import SpeakerRole, Utterance
from app.services.call_workflow_service import CallAnalysisResult, CallWorkflowService
import time

from app.domain.user import User, UserRole
from app.security.jwt import create_access_token
from app.security.stream_token import create_live_call_ticket

CALL_ID = "call-1"
USER_ID = "test-icr"
LIVE_URL = f"/api/v1/calls/{CALL_ID}/live"


def _live_url(_: str | None = None, user_id: str = USER_ID, call_id: str = CALL_ID) -> str:
    """A live URL carrying a fresh single-use ticket (never the access token)."""
    ticket = create_live_call_ticket(user_id, call_id).token
    return f"/api/v1/calls/{call_id}/live?ticket={ticket}"

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
    def __init__(self, *responses: list[ComplaintDetectionResult]) -> None:
        self._responses = responses
        self._calls = 0

    def detect(self, conversation: Conversation) -> list[ComplaintDetectionResult]:
        self._calls += 1
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


class SpyWorkflowService(CallWorkflowService):
    def __init__(self, inner: CallWorkflowService, fail_first: Exception | None = None):
        self._inner = inner
        self._fail_first = fail_first
        self.received: list[tuple[str, Utterance]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def process_utterance(self, call_id: str, utterance: Utterance) -> CallAnalysisResult:
        self.received.append((call_id, utterance))
        if self._fail_first is not None:
            error, self._fail_first = self._fail_first, None
            raise error
        return self._inner.process_utterance(call_id, utterance)


def _setup(
    *responses: list[ComplaintDetectionResult],
    fail_first: Exception | None = None,
    start_call: bool = True,
) -> tuple[TestClient, SpyWorkflowService, str]:
    api_services = build_api_services(
        complaint_provider=FakeComplaintProvider(*responses),
        sentiment_provider=FakeSentimentProvider(),
        question_provider=FakeQuestionProvider(),
    )

    spy = SpyWorkflowService(
        api_services.workflow_service,
        fail_first=fail_first,
    )

    app = create_app(
        ApiServices(
            call_service=api_services.call_service,
            workflow_service=spy,
            user_repository=api_services.user_repository,
            live_state_store=api_services.live_state_store,
            live_call_push_interval_seconds=0.02,
        )
    )

    user = User(
        user_id=USER_ID,
        email="test-icr@example.com",
        password_hash="test-password-hash",
        role=UserRole.ICR,
        is_active=True,
        created_at=time.time(),
    )

    app.state.services.user_repository.save(user)

    token = create_access_token(user)

    client = TestClient(
        app,
        headers={"Authorization": f"Bearer {token}"},
    )

    if start_call:
        assert (
            client.post(
                "/api/v1/calls",
                json={"call_id": CALL_ID},
            ).status_code
            == 201
        )

    return client, spy, token


def _message(index: int = 0, **overrides: Any) -> dict[str, Any]:
    message: dict[str, Any] = {
        "type": "utterance",
        "utterance_id": str(index + 1),
        "transcript": f"Customer statement {index + 1}.",
        "speaker_role": "CUSTOMER",
        "languages": ["en"],
        "start_time": index * 5.0,
        "end_time": index * 5.0 + 4.0,
    }
    message.update(overrides)
    return message


def test_valid_utterance_is_accepted():
    client, _, token = _setup()

    with client.websocket_connect(_live_url(token)) as ws:
        ws.send_json(_message())
        event = ws.receive_json()

    assert event["type"] == "analysis"
    assert event["call_id"] == CALL_ID
    assert event["utterance_id"] == "1"


def test_utterance_reaches_call_workflow_service():
    client, spy, token = _setup()

    with client.websocket_connect(_live_url(token)) as ws:
        ws.send_json(_message(transcript="My car is late.", languages=["en", "ta"]))
        ws.receive_json()

    assert len(spy.received) == 1
    call_id, utterance = spy.received[0]
    assert call_id == CALL_ID
    assert utterance.utterance_id == "1"
    assert utterance.transcript == "My car is late."
    assert utterance.speaker_role is SpeakerRole.CUSTOMER
    assert utterance.languages == ("en", "ta")


def test_response_contains_complaint_coverage():
    client, _, token = _setup([_TURNAROUND, _COMMUNICATION])

    with client.websocket_connect(_live_url(token)) as ws:
        ws.send_json(_message())
        event = ws.receive_json()

    assert event["coverage"] == {
        "call_id": CALL_ID,
        "complaints": [
            {"category": "Turnaround Time", "status": "detected"},
            {"category": "Communication", "status": "detected"},
        ],
    }


def test_response_contains_sentiment():
    client, _, token = _setup()

    with client.websocket_connect(_live_url(token)) as ws:
        ws.send_json(_message())
        event = ws.receive_json()

    assert event["sentiment"] == {
        "label": "NEGATIVE",
        "confidence": 0.9,
        "evidence": "The customer reported a delayed service.",
    }


def test_response_contains_next_question_suggestion():
    client, _, token = _setup([_TURNAROUND])

    with client.websocket_connect(_live_url(token)) as ws:
        ws.send_json(_message())
        suggestion = ws.receive_json()["question_suggestion"]

    assert suggestion["target_category"] == "Turnaround Time"
    assert suggestion["source"] == "rule_based"
    assert suggestion["question"]
    assert suggestion["reason"]


def test_suggestion_is_null_when_no_complaint_is_actionable():
    client, _, token = _setup()

    with client.websocket_connect(_live_url(token)) as ws:
        ws.send_json(_message())
        event = ws.receive_json()

    assert event["question_suggestion"] is None
    assert event["coverage"]["complaints"] == []


def test_multiple_utterances_on_the_same_connection():
    client, spy, token = _setup([_TURNAROUND], [_TURNAROUND, _COMMUNICATION])

    with client.websocket_connect(_live_url(token)) as ws:
        ws.send_json(_message(0))
        first = ws.receive_json()
        ws.send_json(_message(1))
        second = ws.receive_json()

    assert [c["category"] for c in first["coverage"]["complaints"]] == ["Turnaround Time"]
    assert [c["category"] for c in second["coverage"]["complaints"]] == [
        "Turnaround Time",
        "Communication",
    ]
    assert (first["utterance_id"], second["utterance_id"]) == ("1", "2")
    assert len(spy.received) == 2
    assert client.get(f"/api/v1/calls/{CALL_ID}").json()["utterance_count"] == 2


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        "42",
        json.dumps({k: v for k, v in _message().items() if k != "type"}),
        json.dumps(_message(type="ping")),
        json.dumps({k: v for k, v in _message().items() if k != "transcript"}),
        json.dumps(_message(speaker_role="MANAGER")),
        json.dumps(_message(languages=[])),
        json.dumps(_message(transcript="")),
        json.dumps(_message(confidence=1.5)),
        json.dumps(_message(conversation_id=CALL_ID)),
    ],
)
def test_invalid_message_is_rejected_and_connection_stays_open(raw):
    client, spy, token = _setup()

    with client.websocket_connect(_live_url(token)) as ws:
        ws.send_text(raw)
        error = ws.receive_json()
        ws.send_json(_message())
        recovered = ws.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "invalid_message"
    assert error["call_id"] == CALL_ID
    assert error["message"]
    assert recovered["type"] == "analysis"
    assert len(spy.received) == 1


def test_binary_message_is_rejected():
    client, spy, token = _setup()

    with client.websocket_connect(_live_url(token)) as ws:
        ws.send_bytes(b"\x00\x01")
        error = ws.receive_json()

    assert error["code"] == "invalid_message"
    assert spy.received == []


@pytest.mark.parametrize(
    "overrides",
    [{"languages": ["xx"]}, {"start_time": 10.0, "end_time": 5.0}],
)
def test_utterance_violating_domain_rules_is_rejected(overrides):
    client, spy, token = _setup()

    with client.websocket_connect(_live_url(token)) as ws:
        ws.send_json(_message(**overrides))
        error = ws.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "invalid_utterance"
    assert spy.received == []


def test_out_of_order_utterance_is_rejected():
    client, _, token = _setup()

    with client.websocket_connect(_live_url(token)) as ws:
        ws.send_json(_message(1))
        ws.receive_json()
        ws.send_json(_message(0))
        error = ws.receive_json()

    assert error["code"] == "invalid_utterance"


def test_unknown_call_is_reported_and_connection_closed():
    client, spy, token = _setup(start_call=False)

    with client.websocket_connect(_live_url(token)) as ws:
        error = ws.receive_json()
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "call_not_found"
    assert error["call_id"] == CALL_ID
    assert closed.value.code == 4404
    assert spy.received == []


def test_unexpected_failure_returns_generic_error_and_connection_survives():
    client, _, token = _setup(fail_first=RuntimeError("secret provider detail"))

    with client.websocket_connect(_live_url(token)) as ws:
        ws.send_json(_message(0))
        error = ws.receive_json()
        ws.send_json(_message(1))
        recovered = ws.receive_json()

    assert error["code"] == "internal_error"
    assert "secret" not in error["message"]
    assert recovered["type"] == "analysis"


def test_websocket_is_only_available_under_api_v1():
    client, _, token = _setup()

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/calls/{CALL_ID}/live"):
            pass

# ---- Authentication: single-use live-call tickets ----


def _expect_auth_close(client: TestClient, url: str) -> None:
    with client.websocket_connect(url) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 4401


def test_ticket_endpoint_issues_a_short_lived_ticket():
    client, _, _ = _setup()

    response = client.post(f"/api/v1/calls/{CALL_ID}/live-token")

    assert response.status_code == 200
    body = response.json()
    assert body["token"] and 0 < body["expires_in"] <= 300
    with client.websocket_connect(f"{LIVE_URL}?ticket={body['token']}") as ws:
        ws.send_json(_message())
        assert ws.receive_json()["type"] == "analysis"


def test_ticket_endpoint_requires_a_signed_in_user_and_a_known_call():
    client, _, _ = _setup()

    assert TestClient(client.app).post(f"/api/v1/calls/{CALL_ID}/live-token").status_code == 401
    assert client.post("/api/v1/calls/unknown/live-token").status_code == 404


def test_connection_without_a_ticket_is_refused():
    client, spy, _ = _setup()

    _expect_auth_close(client, LIVE_URL)
    assert spy.received == []


def test_access_token_in_the_url_is_refused():
    client, _, token = _setup()

    _expect_auth_close(client, f"{LIVE_URL}?token={token}")
    _expect_auth_close(client, f"{LIVE_URL}?ticket={token}")


@pytest.mark.parametrize("ticket", ["garbage", "a.b.c", ""])
def test_invalid_ticket_is_refused(ticket):
    client, _, _ = _setup()

    _expect_auth_close(client, f"{LIVE_URL}?ticket={ticket}")


def test_ticket_signed_with_another_key_is_refused():
    import jwt

    client, _, _ = _setup()
    forged = jwt.encode(
        {
            "sub": USER_ID,
            "call_id": CALL_ID,
            "purpose": "live_call_ws",
            "jti": "x",
            "exp": int(time.time()) + 60,
        },
        "some-other-secret-key-that-is-long-enough",
        algorithm="HS256",
    )

    _expect_auth_close(client, f"{LIVE_URL}?ticket={forged}")


def test_expired_ticket_is_refused():
    import jwt

    from app.core.config import get_settings

    client, _, _ = _setup()
    expired = jwt.encode(
        {
            "sub": USER_ID,
            "call_id": CALL_ID,
            "purpose": "live_call_ws",
            "jti": "expired",
            "iat": int(time.time()) - 120,
            "exp": int(time.time()) - 60,
        },
        get_settings().auth_secret_key,
        algorithm="HS256",
    )

    _expect_auth_close(client, f"{LIVE_URL}?ticket={expired}")


def test_ticket_for_another_call_is_refused():
    client, _, _ = _setup()
    other_call_ticket = create_live_call_ticket(USER_ID, "call-2").token

    _expect_auth_close(client, f"{LIVE_URL}?ticket={other_call_ticket}")


def test_ticket_for_an_unknown_or_inactive_user_is_refused():
    import dataclasses

    client, _, _ = _setup()
    _expect_auth_close(client, _live_url(user_id="someone-else"))

    repository = client.app.state.services.user_repository
    repository.save(dataclasses.replace(repository.get_by_id(USER_ID), is_active=False))
    _expect_auth_close(client, _live_url())


def test_ticket_is_single_use():
    client, _, _ = _setup()
    url = _live_url()

    with client.websocket_connect(url) as ws:
        ws.send_json(_message())
        assert ws.receive_json()["type"] == "analysis"

    _expect_auth_close(client, url)


def test_ticket_is_not_accepted_as_an_access_token():
    client, _, _ = _setup()
    ticket = create_live_call_ticket(USER_ID, CALL_ID).token

    response = TestClient(client.app).get(
        f"/api/v1/calls/{CALL_ID}", headers={"Authorization": f"Bearer {ticket}"}
    )

    assert response.status_code == 401


def _receive_until_analysed(ws, limit: int = 5) -> dict:
    """Speech is pushed as soon as it is stored, and again once analysed."""
    for _ in range(limit):
        event = ws.receive_json()
        if event.get("sentiment") is not None:
            return event
    raise AssertionError("no analysed event was pushed")


# ---- Server push ----


def test_speech_processed_elsewhere_is_pushed_to_the_socket():
    client, _, _ = _setup([_TURNAROUND])

    with client.websocket_connect(_live_url()) as ws:
        # e.g. the telephony stream, or another API instance.
        assert client.post(
            f"/api/v1/calls/{CALL_ID}/utterances",
            json={k: v for k, v in _message().items() if k != "type"},
        ).status_code == 200
        event = _receive_until_analysed(ws)

    assert event["type"] == "analysis"
    assert event["utterance_id"] == "1"
    assert event["sentiment"]["label"] == "NEGATIVE"
    assert event["question_suggestion"]["target_category"] == "Turnaround Time"


def test_completion_is_pushed_to_the_socket():
    client, _, _ = _setup()
    client.post(
        f"/api/v1/calls/{CALL_ID}/utterances",
        json={k: v for k, v in _message().items() if k != "type"},
    )

    with client.websocket_connect(_live_url()) as ws:
        assert client.post(
            f"/api/v1/calls/{CALL_ID}/complete", json={"end_time": 99.0}
        ).status_code == 200
        event = ws.receive_json()

    assert event["type"] == "analysis"
    assert event["post_call_summary"] is not None


def test_socket_on_one_instance_receives_speech_processed_on_another():
    from app.services.in_memory_conversation_coverage_repository import (
        InMemoryConversationCoverageRepository,
    )
    from app.services.in_memory_conversation_repository import (
        InMemoryConversationRepository,
    )
    from app.domain.user_repository import InMemoryUserRepository
    from app.services.live_state_store import InMemoryLiveStateStore

    # What instances share in production: the database and Redis.
    shared = dict(
        conversation_repository=InMemoryConversationRepository(),
        coverage_repository=InMemoryConversationCoverageRepository(),
        user_repository=InMemoryUserRepository(),
        live_state_store=InMemoryLiveStateStore(),
    )

    def instance():
        services = build_api_services(
            complaint_provider=FakeComplaintProvider([_TURNAROUND]),
            sentiment_provider=FakeSentimentProvider(),
            question_provider=FakeQuestionProvider(),
            **shared,
        )
        import dataclasses

        return create_app(dataclasses.replace(services, live_call_push_interval_seconds=0.02))

    app_a, app_b = instance(), instance()
    user = User(
        user_id=USER_ID,
        email="icr@example.com",
        password_hash="x",
        role=UserRole.ICR,
        is_active=True,
        created_at=time.time(),
    )
    shared["user_repository"].save(user)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    client_a = TestClient(app_a, headers=headers)
    client_b = TestClient(app_b, headers=headers)
    assert client_a.post("/api/v1/calls", json={"call_id": CALL_ID}).status_code == 201

    # The browser gets its ticket from one instance and connects to the other.
    ticket = client_a.post(f"/api/v1/calls/{CALL_ID}/live-token").json()["token"]
    with client_b.websocket_connect(f"{LIVE_URL}?ticket={ticket}") as ws:
        client_a.post(
            f"/api/v1/calls/{CALL_ID}/utterances",
            json={k: v for k, v in _message().items() if k != "type"},
        )
        event = _receive_until_analysed(ws)

    assert event["sentiment"]["label"] == "NEGATIVE"
    assert event["question_suggestion"]["target_category"] == "Turnaround Time"
    # And plain polling on instance B sees the same live analysis.
    polled = client_b.get(f"/api/v1/calls/{CALL_ID}/analysis").json()
    assert polled["sentiment"] == event["sentiment"]
    assert polled["question_suggestion"] == event["question_suggestion"]
