import base64
import json
import re

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.ai.asr.provider import ASRProvider, ASRResult
from app.ai.complaint.provider import ComplaintDetectionProvider, ComplaintDetectionResult
from app.ai.language.provider import (
    LanguageIdentificationProvider,
    LanguageIdentificationResult,
    LanguageSpan,
)
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
from app.services.telephony_audio_buffer import TelephonyAudioBuffer
from app.services.telephony_call_mapping_repository import (
    InMemoryTelephonyCallMappingRepository,
    TelephonyCallMappingRepository,
)
from app.services.telephony_call_service import TelephonyCallService
from app.telephony.plivo.audio import PlivoAudioDecodingError, decode_media_payload
from app.telephony.plivo.provider import PlivoConfigurationError, PlivoTelephonyProvider
from app.telephony.plivo.signature import NONCE_HEADER, SIGNATURE_HEADER, compute_signature
from app.telephony.provider import (
    CallProviderStatus,
    CallStatusEvent,
    InboundCallEvent,
    MediaStreamEvent,
    TelephonyProvider,
    TelephonyStreamError,
    TelephonyWebhookError,
)
from typing import cast
from app.api.dependencies import ApiServices
#app_services = cast(ApiServices, client.app.state.services)  # type: ignore[attr-defined]

try:
    import audioop  # stdlib on Python <3.13, or the audioop-lts backport on 3.13+
except ImportError:  # pragma: no cover - environment guard, not app behavior
    audioop = None

ANSWER_PATH = "/api/v1/telephony/plivo/answer"
STATUS_PATH = "/api/v1/telephony/plivo/status"
ANSWER_URL = "http://testserver" + ANSWER_PATH
STATUS_URL = "http://testserver" + STATUS_PATH

requires_audioop = pytest.mark.skipif(
    audioop is None, reason="audioop (or audioop-lts) is not installed in this environment."
)


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


def _mulaw_b64(num_samples: int) -> str:
    assert audioop is not None
    pcm_silence = b"\x00\x00" * num_samples
    mulaw = audioop.lin2ulaw(pcm_silence, 2)
    return base64.b64encode(mulaw).decode("ascii")


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


# ---- Media-stream event parsing (provider abstraction unit tests) ----

def test_parse_media_stream_event_start_returns_sample_rate():
    provider = PlivoTelephonyProvider(_plivo_settings())

    event = provider.parse_media_stream_event(
        {"event": "start", "start": {"mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000}}}
    )

    assert isinstance(event, MediaStreamEvent)
    assert event.event_type == "start"
    assert event.sample_rate == 8000


def test_parse_media_stream_event_rejects_unsupported_encoding():
    provider = PlivoTelephonyProvider(_plivo_settings())

    with pytest.raises(TelephonyStreamError):
        provider.parse_media_stream_event(
            {"event": "start", "start": {"mediaFormat": {"encoding": "pcma", "sampleRate": 8000}}}
        )


def test_parse_media_stream_event_rejects_unknown_event_type():
    provider = PlivoTelephonyProvider(_plivo_settings())

    with pytest.raises(TelephonyStreamError):
        provider.parse_media_stream_event({"event": "checkpoint"})


def test_parse_media_stream_event_media_requires_payload():
    provider = PlivoTelephonyProvider(_plivo_settings())

    with pytest.raises(TelephonyStreamError):
        provider.parse_media_stream_event({"event": "media", "media": {}})


@requires_audioop
def test_parse_media_stream_event_decodes_audio_and_sequence():
    provider = PlivoTelephonyProvider(_plivo_settings())
    payload = _mulaw_b64(10)

    event = provider.parse_media_stream_event(
        {"event": "media", "media": {"chunk": "5", "payload": payload}}
    )

    assert event.event_type == "media"
    assert event.sequence == 5
    assert event.audio is not None
    assert len(event.audio) == 20  # 10 mu-law samples -> 10 PCM16 samples -> 20 bytes


def test_parse_media_stream_event_stop():
    provider = PlivoTelephonyProvider(_plivo_settings())

    assert provider.parse_media_stream_event({"event": "stop"}).event_type == "stop"


# ---- Audio decoding (malformed audio handling) ----

def test_decode_media_payload_rejects_invalid_base64():
    with pytest.raises(PlivoAudioDecodingError):
        decode_media_payload("not-valid-base64!!")


def test_decode_media_payload_rejects_empty_payload():
    with pytest.raises(PlivoAudioDecodingError):
        decode_media_payload("")


# ---- TelephonyAudioBuffer (chunking/idempotency unit tests) ----

def test_audio_buffer_flushes_after_threshold():
    buffer = TelephonyAudioBuffer(sample_rate=8000, flush_after_seconds=0.01)  # 160 bytes PCM
    buffer.accept(1, b"\x00" * 160)

    chunk = buffer.flush()

    assert chunk is not None
    assert chunk.start_time == 0.0
    assert chunk.duration == pytest.approx(0.01)


def test_audio_buffer_does_not_flush_before_threshold():
    buffer = TelephonyAudioBuffer(sample_rate=8000, flush_after_seconds=1.0)
    buffer.accept(1, b"\x00" * 10)

    assert buffer.flush() is None


def test_audio_buffer_drops_duplicate_and_out_of_order_sequences():
    buffer = TelephonyAudioBuffer(sample_rate=8000, flush_after_seconds=100.0)

    assert buffer.accept(5, b"\x00" * 10) is True
    assert buffer.accept(5, b"\x00" * 10) is False  # duplicate
    assert buffer.accept(4, b"\x00" * 10) is False  # out of order / replay
    assert buffer.accept(6, b"\x00" * 10) is True


def test_audio_buffer_force_flush_returns_partial_data():
    buffer = TelephonyAudioBuffer(sample_rate=8000, flush_after_seconds=100.0)
    buffer.accept(1, b"\x00" * 10)

    chunk = buffer.flush(force=True)

    assert chunk is not None
    assert buffer.flush() is None  # nothing left


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


# ---- Fakes for full API integration ----

class _FakeComplaintProvider(ComplaintDetectionProvider):
    def detect(self, conversation: Conversation) -> list[ComplaintDetectionResult]:
        return []


class _FakeSentimentProvider(SentimentAnalysisProvider):
    def analyze(self, conversation: Conversation) -> SentimentResult:
        return SentimentResult(SentimentLabel.NEUTRAL, 0.5, "No strong signal yet.")


class _FakeQuestionProvider(QuestionSuggestionProvider):
    def generate(self, context: QuestionGenerationContext) -> QuestionSuggestion | None:
        return None


class _FakeASRProvider(ASRProvider):
    """Records every audio chunk it's asked to transcribe. Assumes "en" is
    a supported language code in this project's SUPPORTED_LANGUAGES set;
    swap it for another supported code if that assumption doesn't hold."""

    def __init__(self, transcript: str = "hello there", should_fail: bool = False) -> None:
        self.calls: list[bytes] = []
        self._transcript = transcript
        self._should_fail = should_fail

    def transcribe(self, audio: bytes) -> ASRResult:
        self.calls.append(audio)
        if self._should_fail:
            raise RuntimeError("simulated ASR provider failure")
        return ASRResult(
            transcript=self._transcript,
            detected_language="en",
            start_time=0.0,
            end_time=1.0,
            confidence=0.9,
        )


class _FakeLanguageProvider(LanguageIdentificationProvider):
    def __init__(self, language: str = "en") -> None:
        self.calls: list[str] = []
        self._language = language

    def identify(self, text: str) -> LanguageIdentificationResult:
        self.calls.append(text)
        return LanguageIdentificationResult([LanguageSpan(self._language, 0.99)])


def _build_client(monkeypatch=None, asr_provider=None, **settings_overrides) -> tuple[TestClient, ApiServices]:
    """Build a full app via the real composition root (build_api_services),
    optionally overriding the ASR provider so streamed audio can be
    asserted on without hitting a real ASR API. Returns (client, services)
    so tests can inspect the same CallService instance the app uses."""
    settings = _plivo_settings(
        telephony_provider="plivo",
        plivo_stream_base_url="wss://voice.example.com",
        **settings_overrides,
    )
    if monkeypatch is not None and asr_provider is not None:
        fake_language = _FakeLanguageProvider()
        monkeypatch.setattr("app.api.wiring.create_asr_provider", lambda s: asr_provider)
        monkeypatch.setattr("app.api.wiring.create_language_provider", lambda s: fake_language)

    services = build_api_services(
        _FakeComplaintProvider(), _FakeSentimentProvider(), _FakeQuestionProvider(), settings
    )
    return TestClient(create_app(services)), services


def _extract_call_id(xml_body: str) -> str:
    match = re.search(r"/api/v1/calls/([^/]+)/telephony-stream", xml_body)
    assert match is not None
    return match.group(1)


def _answer_call(client: TestClient, call_uuid: str) -> str:
    response = client.post(
        ANSWER_PATH,
        data={"CallUUID": call_uuid, "From": "+91123", "To": "+91456"},
        headers=_signed_headers("test-auth-token", ANSWER_URL),
    )
    return _extract_call_id(response.text)


# ---- Full API integration: webhooks ----

def test_answer_webhook_rejects_invalid_signature():
    client, _ = _build_client()

    response = client.post(ANSWER_PATH, data={"CallUUID": "uuid-1", "From": "+91123", "To": "+91456"})

    assert response.status_code == 403


def test_answer_webhook_creates_call_and_returns_stream_xml():
    client, _ = _build_client()
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


def test_answer_webhook_does_not_leak_credentials_on_misconfiguration():
    # No telephony provider configured at all.
    client, _ = _build_client(telephony_provider="exotel")

    response = client.post(
        ANSWER_PATH,
        data={"CallUUID": "uuid-1", "From": "+91123", "To": "+91456"},
        headers=_signed_headers("test-auth-token", ANSWER_URL),
    )

    assert response.status_code == 503
    body = response.text
    assert "test-auth-token" not in body
    assert "not_configured" not in body


def test_status_webhook_ends_call_idempotently():
    client, _ = _build_client()
    call_id = _answer_call(client, "uuid-2")
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
    client, _ = _build_client()
    headers = _signed_headers("test-auth-token", STATUS_URL)

    response = client.post(
        STATUS_PATH, data={"CallUUID": "never-answered", "CallStatus": "completed"}, headers=headers
    )

    assert response.status_code == 200


def test_status_webhook_rejects_invalid_signature():
    client, _ = _build_client()

    response = client.post(STATUS_PATH, data={"CallUUID": "uuid-2", "CallStatus": "completed"})

    assert response.status_code == 403


# ---- Telephony WebSocket: lifecycle & security ----

def test_telephony_stream_rejects_unknown_call():
    client, _ = _build_client()

    with client.websocket_connect("/api/v1/calls/unknown-call/telephony-stream") as ws:
        error = ws.receive_json()
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()

    assert error["code"] == "call_not_found"
    assert closed.value.code == 4404


def test_telephony_stream_accepts_known_call_and_handles_frames():
    client, _ = _build_client()
    call_id = _answer_call(client, "uuid-3")

    with client.websocket_connect(f"/api/v1/calls/{call_id}/telephony-stream") as ws:
        ws.send_text(json.dumps({"event": "start", "start": {"callId": call_id}}))
        ws.send_text(json.dumps({"event": "media", "media": {"payload": "AAAA"}}))
        ws.send_text(json.dumps({"event": "stop"}))


def test_telephony_stream_closes_without_leaking_secrets_when_provider_unconfigured():
    client, _ = _build_client(telephony_provider="exotel")
    # Create the call directly through the shared call service, since the
    # answer webhook itself is unavailable without a configured provider.
    _, services = client, None
    # Use the app's own call_service to seed a call so we reach the stream
    # handler's provider check rather than the call_not_found branch.
    app_services = client.app.state.services  # type: ignore[attr-defined]
    call_id = app_services.telephony_call_service.start_call_from_provider(
        "plivo", InboundCallEvent("uuid-x", "+91123", "+91456")
    )

    with client.websocket_connect(f"/api/v1/calls/{call_id}/telephony-stream") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()

    assert closed.value.code == 1011


# ---- Telephony WebSocket: real audio pipeline ----

@requires_audioop
def test_telephony_stream_forwards_transcribed_audio_to_workflow(monkeypatch):
    fake_asr = _FakeASRProvider(transcript="my car is making a noise")
    client, services = _build_client(
        monkeypatch, asr_provider=fake_asr, plivo_stream_flush_seconds=0.01
    )
    call_id = _answer_call(client, "uuid-audio-1")

    with client.websocket_connect(f"/api/v1/calls/{call_id}/telephony-stream") as ws:
        ws.send_text(
            json.dumps(
                {
                    "event": "start",
                    "start": {"mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000}},
                }
            )
        )
        # 80 mu-law samples -> 160 bytes PCM16 -> exactly the 0.01s flush threshold.
        ws.send_text(
            json.dumps({"event": "media", "media": {"chunk": "1", "payload": _mulaw_b64(80)}})
        )
        ws.send_text(json.dumps({"event": "stop"}))

    assert len(fake_asr.calls) == 1
    conversation = services.call_service.get_call(call_id)
    assert conversation.utterance_count == 1
    assert conversation.latest_utterance is not None
    assert conversation.latest_utterance.transcript == "my car is making a noise"


@requires_audioop
def test_telephony_stream_drops_duplicate_media_frames(monkeypatch):
    fake_asr = _FakeASRProvider()
    client, services = _build_client(
        monkeypatch, asr_provider=fake_asr, plivo_stream_flush_seconds=0.01
    )
    call_id = _answer_call(client, "uuid-audio-2")

    with client.websocket_connect(f"/api/v1/calls/{call_id}/telephony-stream") as ws:
        ws.send_text(
            json.dumps(
                {
                    "event": "start",
                    "start": {"mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000}},
                }
            )
        )
        payload = _mulaw_b64(80)
        ws.send_text(json.dumps({"event": "media", "media": {"chunk": "1", "payload": payload}}))
        # Same sequence number replayed — must not be processed twice.
        ws.send_text(json.dumps({"event": "media", "media": {"chunk": "1", "payload": payload}}))
        ws.send_text(json.dumps({"event": "stop"}))

    assert len(fake_asr.calls) == 1
    assert services.call_service.get_call(call_id).utterance_count == 1


def test_telephony_stream_ignores_unsupported_audio_codec(monkeypatch):
    fake_asr = _FakeASRProvider()
    client, services = _build_client(monkeypatch, asr_provider=fake_asr)
    call_id = _answer_call(client, "uuid-audio-3")

    with client.websocket_connect(f"/api/v1/calls/{call_id}/telephony-stream") as ws:
        ws.send_text(
            json.dumps(
                {"event": "start", "start": {"mediaFormat": {"encoding": "pcma", "sampleRate": 8000}}}
            )
        )
        ws.send_text(json.dumps({"event": "media", "media": {"chunk": "1", "payload": "AAAA"}}))
        ws.send_text(json.dumps({"event": "stop"}))
        # Connection must survive an unsupported codec — the underlying
        # phone call stays up even if we can't process its audio.
        ws.close()

    assert fake_asr.calls == []
    assert services.call_service.get_call(call_id).utterance_count == 0
    assert services.call_service.get_call(call_id).status.value == "active"


def test_telephony_stream_ignores_malformed_media_payload(monkeypatch):
    fake_asr = _FakeASRProvider()
    client, services = _build_client(monkeypatch, asr_provider=fake_asr)
    call_id = _answer_call(client, "uuid-audio-4")

    with client.websocket_connect(f"/api/v1/calls/{call_id}/telephony-stream") as ws:
        ws.send_text(
            json.dumps(
                {
                    "event": "start",
                    "start": {"mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000}},
                }
            )
        )
        ws.send_text(
            json.dumps({"event": "media", "media": {"chunk": "1", "payload": "not-valid-base64!!"}})
        )
        ws.send_text("not even json")
        ws.send_text(json.dumps({"event": "stop"}))
        ws.close()

    assert fake_asr.calls == []
    assert services.call_service.get_call(call_id).utterance_count == 0


@requires_audioop
def test_telephony_stream_survives_asr_failure(monkeypatch):
    fake_asr = _FakeASRProvider(should_fail=True)
    client, services = _build_client(
        monkeypatch, asr_provider=fake_asr, plivo_stream_flush_seconds=0.01
    )
    call_id = _answer_call(client, "uuid-audio-5")

    with client.websocket_connect(f"/api/v1/calls/{call_id}/telephony-stream") as ws:
        ws.send_text(
            json.dumps(
                {
                    "event": "start",
                    "start": {"mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000}},
                }
            )
        )
        ws.send_text(
            json.dumps({"event": "media", "media": {"chunk": "1", "payload": _mulaw_b64(80)}})
        )
        ws.send_text(json.dumps({"event": "stop"}))
        ws.close()  # connection must not crash despite the ASR failure

    assert len(fake_asr.calls) == 1
    assert services.call_service.get_call(call_id).utterance_count == 0


def test_telephony_stream_without_asr_provider_configured_does_not_crash():
    # Default settings leave asr_provider "not_configured" -> wiring falls
    # back to asr_provider=None; the stream must degrade safely, not crash.
    client, services = _build_client(plivo_stream_flush_seconds=0.01)
    call_id = _answer_call(client, "uuid-audio-6")

    with client.websocket_connect(f"/api/v1/calls/{call_id}/telephony-stream") as ws:
        ws.send_text(
            json.dumps(
                {
                    "event": "start",
                    "start": {"mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000}},
                }
            )
        )
        ws.send_text(json.dumps({"event": "media", "media": {"chunk": "1", "payload": "AAAA"}}))
        ws.send_text(json.dumps({"event": "stop"}))
        ws.close()

    assert services.call_service.get_call(call_id).utterance_count == 0


@requires_audioop
def test_telephony_stream_drops_buffered_audio_when_call_already_completed(monkeypatch):
    fake_asr = _FakeASRProvider()
    # High flush threshold so audio stays buffered until the forced flush on "stop".
    client, services = _build_client(monkeypatch, asr_provider=fake_asr, plivo_stream_flush_seconds=100.0)
    call_id = _answer_call(client, "uuid-audio-7")

    with client.websocket_connect(f"/api/v1/calls/{call_id}/telephony-stream") as ws:
        ws.send_text(
            json.dumps(
                {
                    "event": "start",
                    "start": {"mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000}},
                }
            )
        )
        ws.send_text(
            json.dumps({"event": "media", "media": {"chunk": "1", "payload": _mulaw_b64(80)}})
        )

        # The provider's status callback (call ended) arrives while audio
        # is still buffered in this open stream.
        client.post(
            STATUS_PATH,
            data={"CallUUID": "uuid-audio-7", "CallStatus": "completed", "Duration": "5"},
            headers=_signed_headers("test-auth-token", STATUS_URL),
        )

        ws.send_text(json.dumps({"event": "stop"}))
        ws.close()

    # The buffered audio must not be transcribed into an already-completed call.
    assert fake_asr.calls == []
    conversation = services.call_service.get_call(call_id)
    assert conversation.status.value == "completed"
    assert conversation.utterance_count == 0