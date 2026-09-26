from collections.abc import Mapping
from typing import Any

from app.core.config import Settings, get_settings
from app.telephony.plivo.audio import (
    PlivoAudioDecodingError,
    decode_media_payload,
    is_supported_encoding,
)
from app.telephony.plivo.signature import validate_signature as _validate_plivo_signature
from app.telephony.provider import (
    CallProviderStatus,
    CallStatusEvent,
    InboundCallEvent,
    MediaStreamEvent,
    TelephonyProvider,
    TelephonyResponse,
    TelephonyStreamError,
    TelephonyWebhookError,
)

_UNCONFIGURED = "not_configured"

_STATUS_MAP: dict[str, CallProviderStatus] = {
    "ringing": CallProviderStatus.RINGING,
    "in-progress": CallProviderStatus.IN_PROGRESS,
    "completed": CallProviderStatus.COMPLETED,
    "failed": CallProviderStatus.FAILED,
    "busy": CallProviderStatus.BUSY,
    "no-answer": CallProviderStatus.NO_ANSWER,
}

_DEFAULT_SAMPLE_RATE = 8000


class PlivoConfigurationError(Exception):
    pass


class PlivoTelephonyProvider(TelephonyProvider):
    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        auth_token = settings.plivo_auth_token.strip()
        if not auth_token or auth_token == _UNCONFIGURED:
            raise PlivoConfigurationError("Plivo auth token is not configured.")
        self._auth_token = auth_token
        self._validate_signatures = settings.plivo_validate_signatures

    def validate_signature(
        self, headers: Mapping[str, str], url: str, params: Mapping[str, str]
    ) -> bool:
        if not self._validate_signatures:
            return True
        return _validate_plivo_signature(self._auth_token, headers, url)

    def parse_inbound_call(self, params: Mapping[str, str]) -> InboundCallEvent:
        call_uuid = params.get("CallUUID", "")
        if not call_uuid.strip():
            raise TelephonyWebhookError("Plivo answer webhook missing CallUUID.")
        return InboundCallEvent(
            provider_call_id=call_uuid,
            from_number=params.get("From", ""),
            to_number=params.get("To", ""),
        )

    def parse_call_status(self, params: Mapping[str, str]) -> CallStatusEvent:
        call_uuid = params.get("CallUUID", "")
        if not call_uuid.strip():
            raise TelephonyWebhookError("Plivo status webhook missing CallUUID.")

        status = _STATUS_MAP.get(
            (params.get("CallStatus") or "").strip().lower(), CallProviderStatus.UNKNOWN
        )
        duration_seconds = None
        raw_duration = params.get("Duration")
        if raw_duration is not None:
            try:
                duration_seconds = float(raw_duration)
            except ValueError:
                duration_seconds = None

        return CallStatusEvent(
            provider_call_id=call_uuid, status=status, duration_seconds=duration_seconds
        )

    def build_stream_response(self, stream_url: str) -> TelephonyResponse:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f'<Stream bidirectional="false" keepCallAlive="true">{stream_url}</Stream>'
            "</Response>"
        )
        return TelephonyResponse(content=xml, content_type="application/xml")

    def parse_media_stream_event(self, raw_event: Mapping[str, Any]) -> MediaStreamEvent:
        event_type = str(raw_event.get("event", "")).strip().lower()

        if event_type == "start":
            return self._parse_start(raw_event)
        if event_type == "media":
            return self._parse_media(raw_event)
        if event_type == "stop":
            return MediaStreamEvent(event_type="stop")

        raise TelephonyStreamError(f"Unknown Plivo stream event: {event_type!r}.")

    @staticmethod
    def _parse_start(raw_event: Mapping[str, Any]) -> MediaStreamEvent:
        start = raw_event.get("start") or {}
        media_format = start.get("mediaFormat") or {}
        encoding = media_format.get("encoding")

        if not is_supported_encoding(encoding):
            raise TelephonyStreamError(
                f"Unsupported Plivo media encoding: {encoding!r}. Only mu-law is supported."
            )

        try:
            sample_rate = int(media_format.get("sampleRate", _DEFAULT_SAMPLE_RATE))
        except (TypeError, ValueError):
            sample_rate = _DEFAULT_SAMPLE_RATE

        return MediaStreamEvent(event_type="start", sample_rate=sample_rate)

    @staticmethod
    def _parse_media(raw_event: Mapping[str, Any]) -> MediaStreamEvent:
        media = raw_event.get("media") or {}
        payload = media.get("payload")
        if not isinstance(payload, str) or not payload:
            raise TelephonyStreamError("Plivo media event is missing an audio payload.")

        raw_chunk = media.get("chunk")
        try:
            sequence = int(raw_chunk) if raw_chunk is not None else None
        except (TypeError, ValueError):
            sequence = None

        try:
            audio = decode_media_payload(payload)
        except PlivoAudioDecodingError as exc:
            raise TelephonyStreamError(str(exc)) from exc

        return MediaStreamEvent(event_type="media", sequence=sequence, audio=audio)