from collections.abc import Mapping

from app.core.config import Settings, get_settings
from app.telephony.plivo.signature import validate_signature as _validate_plivo_signature
from app.telephony.provider import (
    CallProviderStatus,
    CallStatusEvent,
    InboundCallEvent,
    TelephonyProvider,
    TelephonyResponse,
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