from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class CallDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallProviderStatus(str, Enum):
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class InboundCallEvent:
    provider_call_id: str
    from_number: str
    to_number: str
    direction: CallDirection = CallDirection.INBOUND

    def __post_init__(self) -> None:
        if not self.provider_call_id.strip():
            raise ValueError("provider_call_id must not be empty.")


@dataclass(frozen=True)
class CallStatusEvent:
    provider_call_id: str
    status: CallProviderStatus
    duration_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.provider_call_id.strip():
            raise ValueError("provider_call_id must not be empty.")
        if not isinstance(self.status, CallProviderStatus):
            raise TypeError("status must be a CallProviderStatus.")


@dataclass(frozen=True)
class TelephonyResponse:
    content: str
    content_type: str


@dataclass(frozen=True)
class MediaStreamEvent:
    """A single decoded event from a provider's live media-stream socket.

    Provider-agnostic: audio is always 16-bit signed PCM, mono, at
    ``sample_rate`` (only meaningful on "start"). Providers translate their
    own wire format (Plivo's base64 mu-law, Exotel's own framing, etc.)
    into this shape so the rest of the system never has to know which
    provider is on the other end of the socket.
    """

    event_type: str  # "start" | "media" | "stop"
    sequence: int | None = None
    audio: bytes | None = None
    sample_rate: int | None = None


class TelephonyWebhookError(Exception):
    pass


class TelephonyStreamError(Exception):
    """Raised for a malformed, unsupported, or unrecognized media-stream
    frame. Callers should log and continue — a bad frame must never tear
    down the underlying phone call."""

    pass


class TelephonyProvider(ABC):
    @abstractmethod
    def validate_signature(
        self, headers: Mapping[str, str], url: str, params: Mapping[str, str]
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def parse_inbound_call(self, params: Mapping[str, str]) -> InboundCallEvent:
        raise NotImplementedError

    @abstractmethod
    def parse_call_status(self, params: Mapping[str, str]) -> CallStatusEvent:
        raise NotImplementedError

    @abstractmethod
    def build_stream_response(self, stream_url: str) -> TelephonyResponse:
        raise NotImplementedError

    @abstractmethod
    def parse_media_stream_event(self, raw_event: Mapping[str, Any]) -> MediaStreamEvent:
        """Parse one JSON message from the provider's live media-stream
        WebSocket into a provider-agnostic MediaStreamEvent.

        Raises TelephonyStreamError for anything malformed, unrecognized,
        or using an unsupported audio codec.
        """
        raise NotImplementedError