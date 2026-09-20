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

CALL_ID = "call-1"
LIVE_URL = f"/api/v1/calls/{CALL_ID}/live"

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
) -> tuple[TestClient, SpyWorkflowService]:
    services = build_api_services(
        FakeComplaintProvider(*responses),
        FakeSentimentProvider(),
        FakeQuestionProvider(),
    )
    spy = SpyWorkflowService(services.workflow_service, fail_first)
    client = TestClient(
        create_app(ApiServices(call_service=services.call_service, workflow_service=spy))
    )
    if start_call:
        assert client.post("/api/v1/calls", json={"call_id": CALL_ID}).status_code == 201
    return client, spy


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
    client, _ = _setup()

    with client.websocket_connect(LIVE_URL) as ws:
        ws.send_json(_message())
        event = ws.receive_json()

    assert event["type"] == "analysis"
    assert event["call_id"] == CALL_ID
    assert event["utterance_id"] == "1"


def test_utterance_reaches_call_workflow_service():
    client, spy = _setup()

    with client.websocket_connect(LIVE_URL) as ws:
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
    client, _ = _setup([_TURNAROUND, _COMMUNICATION])

    with client.websocket_connect(LIVE_URL) as ws:
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
    client, _ = _setup()

    with client.websocket_connect(LIVE_URL) as ws:
        ws.send_json(_message())
        event = ws.receive_json()

    assert event["sentiment"] == {
        "label": "NEGATIVE",
        "confidence": 0.9,
        "evidence": "The customer reported a delayed service.",
    }


def test_response_contains_next_question_suggestion():
    client, _ = _setup([_TURNAROUND])

    with client.websocket_connect(LIVE_URL) as ws:
        ws.send_json(_message())
        suggestion = ws.receive_json()["question_suggestion"]

    assert suggestion["target_category"] == "Turnaround Time"
    assert suggestion["source"] == "rule_based"
    assert suggestion["question"]
    assert suggestion["reason"]


def test_suggestion_is_null_when_no_complaint_is_actionable():
    client, _ = _setup()

    with client.websocket_connect(LIVE_URL) as ws:
        ws.send_json(_message())
        event = ws.receive_json()

    assert event["question_suggestion"] is None
    assert event["coverage"]["complaints"] == []


def test_multiple_utterances_on_the_same_connection():
    client, spy = _setup([_TURNAROUND], [_TURNAROUND, _COMMUNICATION])

    with client.websocket_connect(LIVE_URL) as ws:
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
    client, spy = _setup()

    with client.websocket_connect(LIVE_URL) as ws:
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
    client, spy = _setup()

    with client.websocket_connect(LIVE_URL) as ws:
        ws.send_bytes(b"\x00\x01")
        error = ws.receive_json()

    assert error["code"] == "invalid_message"
    assert spy.received == []


@pytest.mark.parametrize(
    "overrides",
    [{"languages": ["xx"]}, {"start_time": 10.0, "end_time": 5.0}],
)
def test_utterance_violating_domain_rules_is_rejected(overrides):
    client, spy = _setup()

    with client.websocket_connect(LIVE_URL) as ws:
        ws.send_json(_message(**overrides))
        error = ws.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "invalid_utterance"
    assert spy.received == []


def test_out_of_order_utterance_is_rejected():
    client, _ = _setup()

    with client.websocket_connect(LIVE_URL) as ws:
        ws.send_json(_message(1))
        ws.receive_json()
        ws.send_json(_message(0))
        error = ws.receive_json()

    assert error["code"] == "invalid_utterance"


def test_unknown_call_is_reported_and_connection_closed():
    client, spy = _setup(start_call=False)

    with client.websocket_connect(LIVE_URL) as ws:
        error = ws.receive_json()
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "call_not_found"
    assert error["call_id"] == CALL_ID
    assert closed.value.code == 4404
    assert spy.received == []


def test_unexpected_failure_returns_generic_error_and_connection_survives():
    client, _ = _setup(fail_first=RuntimeError("secret provider detail"))

    with client.websocket_connect(LIVE_URL) as ws:
        ws.send_json(_message(0))
        error = ws.receive_json()
        ws.send_json(_message(1))
        recovered = ws.receive_json()

    assert error["code"] == "internal_error"
    assert "secret" not in error["message"]
    assert recovered["type"] == "analysis"


def test_websocket_is_only_available_under_api_v1():
    client, _ = _setup()

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/calls/{CALL_ID}/live"):
            pass