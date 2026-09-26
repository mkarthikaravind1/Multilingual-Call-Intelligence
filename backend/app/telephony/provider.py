from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum


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


class TelephonyWebhookError(Exception):
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