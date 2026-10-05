from xml.sax.saxutils import escape
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
    "cancel": CallProviderStatus.CANCELLED,
    "timeout": CallProviderStatus.TIMEOUT,
}

_DEFAULT_SAMPLE_RATE = 8000
# Only mu-law is decoded (see app.telephony.plivo.audio); Plivo's default is
# linear PCM, so the codec is always asked for explicitly.
_STREAM_CONTENT_TYPE = "audio/x-mulaw;rate=8000"
_STREAM_TIMEOUT_SECONDS = 86400
_ATTRIBUTE_ENTITIES = {'"': "&quot;"}
_TRACKS = frozenset({"inbound", "outbound"})


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
        self._icr_dial_targets = tuple(
            target.strip()
            for target in settings.plivo_icr_dial_targets.split(",")
            if target.strip()
        )
        self._icr_caller_id = settings.plivo_icr_caller_id.strip()
        self._icr_dial_timeout = settings.plivo_icr_dial_timeout_seconds

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
        if not self._icr_dial_targets:
            # No ICR to dial: stream the caller only, and hold the call open
            # for as long as the stream runs.
            stream = (
                f'<Stream bidirectional="false" keepCallAlive="true" '
                f'contentType="{_STREAM_CONTENT_TYPE}">{escape(stream_url)}</Stream>'
            )
            return _xml_response(stream)

        # Stream both sides as separate tracks (inbound = the customer,
        # outbound = the ICR), in the background (keepCallAlive="false"), so
        # Plivo goes straight on to dial the ICR.
        stream = (
            f'<Stream bidirectional="false" keepCallAlive="false" audioTrack="both" '
            f'streamTimeout="{_STREAM_TIMEOUT_SECONDS}" '
            f'contentType="{_STREAM_CONTENT_TYPE}">{escape(stream_url)}</Stream>'
        )
        caller_id = (
            f' callerId="{escape(self._icr_caller_id, _ATTRIBUTE_ENTITIES)}"'
            if self._icr_caller_id
            else ""
        )
        targets = "".join(_dial_target(target) for target in self._icr_dial_targets)
        return _xml_response(
            f"{stream}<Dial{caller_id} timeout=\"{self._icr_dial_timeout}\">{targets}</Dial>"
        )

    def parse_media_stream_event(self, raw_event: Mapping[str, Any]) -> MediaStreamEvent:
        return parse_plivo_media_stream_event(raw_event)

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

        raw_tracks = start.get("tracks")
        tracks = (
            tuple(str(t).strip().lower() for t in raw_tracks if str(t).strip().lower() in _TRACKS)
            if isinstance(raw_tracks, list)
            else ()
        )
        return MediaStreamEvent(event_type="start", sample_rate=sample_rate, tracks=tracks)

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

        raw_track = media.get("track")
        track = raw_track.strip().lower() if isinstance(raw_track, str) else None
        return MediaStreamEvent(
            event_type="media",
            sequence=sequence,
            audio=audio,
            track=track if track in _TRACKS else None,
        )


def parse_plivo_media_stream_event(raw_event: Mapping[str, Any]) -> MediaStreamEvent:
    """Parse one Plivo media-stream frame. Needs no Plivo credentials, so test
    calls can stream Plivo-format audio without a Plivo account."""
    event_type = str(raw_event.get("event", "")).strip().lower()

    if event_type == "start":
        return PlivoTelephonyProvider._parse_start(raw_event)
    if event_type == "media":
        return PlivoTelephonyProvider._parse_media(raw_event)
    if event_type == "stop":
        return MediaStreamEvent(event_type="stop")

    raise TelephonyStreamError(f"Unknown Plivo stream event: {event_type!r}.")


def _xml_response(body: str) -> TelephonyResponse:
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>'
    return TelephonyResponse(content=xml, content_type="application/xml")


def _dial_target(target: str) -> str:
    """A phone number, or a SIP endpoint (sip:icr@example.com)."""
    if target.lower().startswith("sip:"):
        return f"<User>{escape(target)}</User>"
    return f"<Number>{escape(target)}</Number>"
