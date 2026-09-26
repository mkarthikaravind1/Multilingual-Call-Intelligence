import json
import re

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.ai.complaint.provider import ComplaintDetectionProvider, ComplaintDetectionResult
from app.ai.question.provider import QuestionGenerationContext, QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentLabel, SentimentResult
from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.composition.providers import (
    UnsupportedProviderError,
    create_call_mapping_repository,
    create_telephony_provider,
)
from app.core.config import Settings
from app.domain.conversation import Conversation
from app.domain.question_suggestion import QuestionSuggestion
from app.domain.telephony_call_mapping import TelephonyCallMapping
from app.services.call_service import CallService
from app.services.conversation_service import ConversationService
from app.services.in_memory_conversation_repository import InMemoryConversationRepository
from app.services.telephony_call_mapping_repository import (
    InMemoryTelephonyCallMappingRepository,
    TelephonyCallMappingRepository,
)
from app.services.telephony_call_service import TelephonyCallService
from app.telephony.plivo.provider import PlivoConfigurationError, PlivoTelephonyProvider
from app.telephony.plivo.signature import NONCE_HEADER, SIGNATURE_HEADER, compute_signature
from app.telephony.provider import (
    CallProviderStatus,
    CallStatusEvent,
    InboundCallEvent,
    TelephonyProvider,
    TelephonyWebhookError,
)

ANSWER_PATH = "/api/v1/telephony/plivo/answer"
STATUS_PATH = "/api/v1/telephony/plivo/status"
ANSWER_URL = "http://testserver" + ANSWER_PATH
STATUS_URL = "http://testserver" + STATUS_PATH


def _plivo_settings(**overrides) -> Settings:
    values = {"plivo_auth_token": "test-auth-token", "plivo_validate_signatures": True}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def _signed_headers(auth_token: str, url: str, nonce: str = "nonce-1") -> dict[str, str]:
    return {
        SIGNATURE_HEADER: compute_signature(auth_token, url, nonce),
        NONCE_HEADER: nonce,
    }


def _call_service() -> CallService:
    return CallService(ConversationService(InMemoryConversationRepository()))


# ---- TelephonyProvider contract ----

def test_telephony_provider_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        TelephonyProvider()  # type: ignore


def test_plivo_provider_satisfies_contract():
    assert isinstance(PlivoTelephonyProvider(_plivo_settings()), TelephonyProvider)


def test_plivo_provider_requires_auth_token():
    with pytest.raises(PlivoConfigurationError):
        PlivoTelephonyProvider(Settings(_env_file=None, plivo_auth_token="not_configured"))  # type: ignore


# ---- Provider factories ----

def test_create_telephony_provider_builds_plivo():
    assert isinstance(create_telephony_provider(_plivo_settings()), PlivoTelephonyProvider)


def test_create_telephony_provider_rejects_unknown_provider():
    with pytest.raises(UnsupportedProviderError, match="telephony provider"):
        create_telephony_provider(Settings(_env_file=None, telephony_provider="exotel"))  # type: ignore


def test_create_call_mapping_repository_defaults_to_in_memory():
    repository = create_call_mapping_repository(Settings(_env_file=None))  # type: ignore
    assert isinstance(repository, InMemoryTelephonyCallMappingRepository)


def test_create_call_mapping_repository_rejects_unknown_provider():
    with pytest.raises(UnsupportedProviderError, match="call mapping store provider"):
        create_call_mapping_repository(
            Settings(_env_file=None, call_mapping_store_provider="bogus")  # type: ignore
        )


# ---- Signature validation ----

def test_valid_signature_is_accepted():
    provider = PlivoTelephonyProvider(_plivo_settings())
    headers = _signed_headers("test-auth-token", ANSWER_URL)

    assert provider.validate_signature(headers, ANSWER_URL, {}) is True


def test_wrong_signature_is_rejected():
    provider = PlivoTelephonyProvider(_plivo_settings())
    headers = _signed_headers("wrong-token", ANSWER_URL)

    assert provider.validate_signature(headers, ANSWER_URL, {}) is False


def test_missing_signature_headers_are_rejected():
    provider = PlivoTelephonyProvider(_plivo_settings())

    assert provider.validate_signature({}, ANSWER_URL, {}) is False


def test_signature_validation_can_be_disabled():
    provider = PlivoTelephonyProvider(_plivo_settings(plivo_validate_signatures=False))

    assert provider.validate_signature({}, ANSWER_URL, {}) is True


# ---- Webhook payload parsing ----

def test_parse_inbound_call_extracts_fields():
    provider = PlivoTelephonyProvider(_plivo_settings())

    event = provider.parse_inbound_call({"CallUUID": "uuid-1", "From": "+91123", "To": "+91456"})

    assert isinstance(event, InboundCallEvent)
    assert event.provider_call_id == "uuid-1"
    assert event.from_number == "+91123"


def test_parse_inbound_call_requires_call_uuid():
    provider = PlivoTelephonyProvider(_plivo_settings())

    with pytest.raises(TelephonyWebhookError):
        provider.parse_inbound_call({"From": "+91123"})


@pytest.mark.parametrize(
    "raw_status, expected",
    [
        ("ringing", CallProviderStatus.RINGING),
        ("in-progress", CallProviderStatus.IN_PROGRESS),
        ("completed", CallProviderStatus.COMPLETED),
        ("busy", CallProviderStatus.BUSY),
        ("no-answer", CallProviderStatus.NO_ANSWER),
        ("something-new", CallProviderStatus.UNKNOWN),
    ],
)
def test_parse_call_status_maps_known_and_unknown_statuses(raw_status, expected):
    provider = PlivoTelephonyProvider(_plivo_settings())

    event = provider.parse_call_status(
        {"CallUUID": "uuid-1", "CallStatus": raw_status, "Duration": "12"}
    )

    assert event.status is expected
    assert event.duration_seconds == 12.0


def test_parse_call_status_requires_call_uuid():
    provider = PlivoTelephonyProvider(_plivo_settings())

    with pytest.raises(TelephonyWebhookError):
        provider.parse_call_status({"CallStatus": "completed"})


def test_build_stream_response_embeds_url_and_keeps_call_alive():
    provider = PlivoTelephonyProvider(_plivo_settings())

    response = provider.build_stream_response("wss://example.com/api/v1/calls/call-1/telephony-stream")

    assert 'bidirectional="false"' in response.content
    assert 'keepCallAlive="true"' in response.content
    assert "wss://example.com/api/v1/calls/call-1/telephony-stream" in response.content
    assert response.content_type == "application/xml"


# ---- Call mapping repository ----

def test_in_memory_repository_satisfies_contract():
    assert isinstance(InMemoryTelephonyCallMappingRepository(), TelephonyCallMappingRepository)


def test_in_memory_mapping_repository_round_trip():
    repository = InMemoryTelephonyCallMappingRepository()
    mapping = TelephonyCallMapping("plivo", "uuid-9", "call-9", created_at=0.0)

    repository.save(mapping)

    assert repository.get_by_provider_call_id("uuid-9") == mapping
    assert repository.get_by_provider_call_id("missing") is None


# ---- TelephonyCallService ----

def test_start_call_from_provider_creates_call_and_mapping():
    call_service = _call_service()
    telephony_call_service = TelephonyCallService(
        call_service, InMemoryTelephonyCallMappingRepository()
    )

    call_id = telephony_call_service.start_call_from_provider(
        "plivo", InboundCallEvent("uuid-1", "+91123", "+91456")
    )

    assert call_service.get_call(call_id).status.value == "active"
    assert telephony_call_service.resolve_call_id("uuid-1") == call_id


def test_resolve_call_id_returns_none_for_unknown_call():
    telephony_call_service = TelephonyCallService(
        _call_service(), InMemoryTelephonyCallMappingRepository()
    )

    assert telephony_call_service.resolve_call_id("unknown") is None


def test_handle_status_event_ends_call_on_terminal_status():
    call_service = _call_service()
    telephony_call_service = TelephonyCallService(
        call_service, InMemoryTelephonyCallMappingRepository()
    )
    call_id = telephony_call_service.start_call_from_provider(
        "plivo", InboundCallEvent("uuid-1", "+91123", "+91456")
    )

    handled = telephony_call_service.handle_status_event(
        CallStatusEvent("uuid-1", CallProviderStatus.COMPLETED, duration_seconds=30.0)
    )

    conversation = call_service.get_call(call_id)
    assert handled is True
    assert conversation.status.value == "completed"
    assert conversation.end_time == 30.0


def test_handle_status_event_is_idempotent_on_repeat():
    call_service = _call_service()
    telephony_call_service = TelephonyCallService(
        call_service, InMemoryTelephonyCallMappingRepository()
    )
    call_id = telephony_call_service.start_call_from_provider(
        "plivo", InboundCallEvent("uuid-1", "+91123", "+91456")
    )
    telephony_call_service.handle_status_event(
        CallStatusEvent("uuid-1", CallProviderStatus.COMPLETED, duration_seconds=30.0)
    )

    telephony_call_service.handle_status_event(
        CallStatusEvent("uuid-1", CallProviderStatus.COMPLETED, duration_seconds=9999.0)
    )

    assert call_service.get_call(call_id).end_time == 30.0


def test_handle_status_event_ignores_non_terminal_status():
    call_service = _call_service()
    telephony_call_service = TelephonyCallService(
        call_service, InMemoryTelephonyCallMappingRepository()
    )
    call_id = telephony_call_service.start_call_from_provider(
        "plivo", InboundCallEvent("uuid-1", "+91123", "+91456")
    )

    handled = telephony_call_service.handle_status_event(
        CallStatusEvent("uuid-1", CallProviderStatus.RINGING)
    )

    assert handled is True
    assert call_service.get_call(call_id).status.value == "active"


def test_handle_status_event_for_unknown_call_is_a_safe_noop():
    telephony_call_service = TelephonyCallService(
        _call_service(), InMemoryTelephonyCallMappingRepository()
    )

    handled = telephony_call_service.handle_status_event(
        CallStatusEvent("unknown-uuid", CallProviderStatus.COMPLETED)
    )

    assert handled is False


# ---- Full API integration ----

class _FakeComplaintProvider(ComplaintDetectionProvider):
    def detect(self, conversation: Conversation) -> list[ComplaintDetectionResult]:
        return []


class _FakeSentimentProvider(SentimentAnalysisProvider):
    def analyze(self, conversation: Conversation) -> SentimentResult:
        return SentimentResult(SentimentLabel.NEUTRAL, 0.5, "No strong signal yet.")


class _FakeQuestionProvider(QuestionSuggestionProvider):
    def generate(self, context: QuestionGenerationContext) -> QuestionSuggestion | None:
        return None


def _build_client(**settings_overrides) -> TestClient:
    settings = _plivo_settings(
        telephony_provider="plivo",
        plivo_stream_base_url="wss://voice.example.com",
        **settings_overrides,
    )
    services = build_api_services(
        _FakeComplaintProvider(), _FakeSentimentProvider(), _FakeQuestionProvider(), settings
    )
    return TestClient(create_app(services))


def _extract_call_id(xml_body: str) -> str:
    match = re.search(r"/api/v1/calls/([^/]+)/telephony-stream", xml_body)
    assert match is not None
    return match.group(1)


def test_answer_webhook_rejects_invalid_signature():
    client = _build_client()

    response = client.post(ANSWER_PATH, data={"CallUUID": "uuid-1", "From": "+91123", "To": "+91456"})

    assert response.status_code == 403


def test_answer_webhook_creates_call_and_returns_stream_xml():
    client = _build_client()
    headers = _signed_headers("test-auth-token", ANSWER_URL)

    response = client.post(
        ANSWER_PATH,
        data={"CallUUID": "uuid-1", "From": "+91123", "To": "+91456"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    call_id = _extract_call_id(response.text)
    assert call_id.startswith("plivo-")

    call = client.get(f"/api/v1/calls/{call_id}").json()
    assert call["status"] == "active"


def test_status_webhook_ends_call_idempotently():
    client = _build_client()
    answer = client.post(
        ANSWER_PATH,
        data={"CallUUID": "uuid-2", "From": "+91123", "To": "+91456"},
        headers=_signed_headers("test-auth-token", ANSWER_URL),
    )
    call_id = _extract_call_id(answer.text)
    status_headers = _signed_headers("test-auth-token", STATUS_URL)

    first = client.post(
        STATUS_PATH,
        data={"CallUUID": "uuid-2", "CallStatus": "completed", "Duration": "42"},
        headers=status_headers,
    )
    second = client.post(
        STATUS_PATH,
        data={"CallUUID": "uuid-2", "CallStatus": "completed", "Duration": "999"},
        headers=status_headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    call = client.get(f"/api/v1/calls/{call_id}").json()
    assert call["status"] == "completed"
    assert call["end_time"] == 42.0


def test_status_webhook_for_unknown_call_still_returns_200():
    client = _build_client()
    headers = _signed_headers("test-auth-token", STATUS_URL)

    response = client.post(
        STATUS_PATH, data={"CallUUID": "never-answered", "CallStatus": "completed"}, headers=headers
    )

    assert response.status_code == 200


def test_status_webhook_rejects_invalid_signature():
    client = _build_client()

    response = client.post(STATUS_PATH, data={"CallUUID": "uuid-2", "CallStatus": "completed"})

    assert response.status_code == 403


# ---- Telephony WebSocket stream ----

def test_telephony_stream_rejects_unknown_call():
    client = _build_client()

    with client.websocket_connect("/api/v1/calls/unknown-call/telephony-stream") as ws:
        error = ws.receive_json()
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()

    assert error["code"] == "call_not_found"
    assert closed.value.code == 4404


def test_telephony_stream_accepts_known_call_and_handles_frames():
    client = _build_client()
    answer = client.post(
        ANSWER_PATH,
        data={"CallUUID": "uuid-3", "From": "+91123", "To": "+91456"},
        headers=_signed_headers("test-auth-token", ANSWER_URL),
    )
    call_id = _extract_call_id(answer.text)

    with client.websocket_connect(f"/api/v1/calls/{call_id}/telephony-stream") as ws:
        ws.send_text(json.dumps({"event": "start", "start": {"callId": call_id}}))
        ws.send_text(json.dumps({"event": "media", "media": {"payload": "AAAA"}}))
        ws.send_text(json.dumps({"event": "stop"}))