from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.domain.conversation import CallDirection
from app.domain.utterance import SpeakerRole

# The two sides of a call a provider can stream separately: "inbound" is
# whoever placed the call, "outbound" whoever they hear.
TRACKS = ("inbound", "outbound")


def track_roles(direction: CallDirection | None) -> dict[str, SpeakerRole]:
    """Who speaks on each track: the customer places an incoming call, the
    executive an outgoing one."""
    if direction is CallDirection.OUTBOUND:
        return {"inbound": SpeakerRole.ICR, "outbound": SpeakerRole.CUSTOMER}
    return {"inbound": SpeakerRole.CUSTOMER, "outbound": SpeakerRole.ICR}


class CallProviderStatus(str, Enum):
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
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
class DialPlan:
    """Who the provider rings once the call's audio is being streamed."""

    # Phone numbers or SIP addresses; empty: the configured ones.
    targets: tuple[str, ...] = ()
    # The number shown to whoever is rung; None: the configured one.
    caller_id: str | None = None
    # Where the provider reports who answered.
    callback_url: str | None = None


@dataclass(frozen=True)
class DialAnswerEvent:
    """One of the rung parties picked up."""

    provider_call_id: str
    answered_target: str


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
    # Which side of the call the audio is from, when the provider streams
    # the two sides separately: "inbound" (the caller) or "outbound" (what
    # the caller hears, i.e. the ICR the call was dialled to). None for a
    # single mixed stream. On "start", tracks lists the tracks to expect.
    track: str | None = None
    tracks: tuple[str, ...] = ()
    # On "start": the provider's audio encoding for this stream, which the
    # stream's media frames are parsed with.
    encoding: str | None = None


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
    def build_stream_response(
        self, stream_url: str, dial: DialPlan | None = None
    ) -> TelephonyResponse:
        raise NotImplementedError

    def parse_dial_answer(self, params: Mapping[str, str]) -> DialAnswerEvent | None:
        """Who answered, from the provider's callback about the parties it
        rang; None for any other stage of the ringing (or a provider that
        does not report it)."""
        return None

    @abstractmethod
    def parse_media_stream_event(
        self, raw_event: Mapping[str, Any], encoding: str | None = None
    ) -> MediaStreamEvent:
        """Parse one JSON message from the provider's live media-stream
        WebSocket into a provider-agnostic MediaStreamEvent. encoding is
        the stream's, from its "start" event (None: the provider default).

        Raises TelephonyStreamError for anything malformed, unrecognized,
        or using an unsupported audio codec.
        """
        raise NotImplementedError