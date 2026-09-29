import logging
import threading
import time
from collections.abc import Callable
from uuid import uuid4

from app.domain.conversation import ConversationStatus
from app.domain.telephony_call_mapping import TelephonyCallMapping
from app.services.call_customer_service import CallCustomerService
from app.services.call_service import CallService
from app.services.telephony_call_mapping_repository import TelephonyCallMappingRepository
from app.telephony.provider import CallProviderStatus, CallStatusEvent, InboundCallEvent

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset(
    {
        CallProviderStatus.COMPLETED,
        CallProviderStatus.FAILED,
        CallProviderStatus.BUSY,
        CallProviderStatus.NO_ANSWER,
        CallProviderStatus.CANCELLED,
        CallProviderStatus.TIMEOUT,
    }
)

# Upper bound on how long a terminal status waits for the call's media stream
# to finish its buffered and in-flight audio before completing anyway.
STREAM_DRAIN_TIMEOUT_SECONDS = 30.0


class TelephonyCallService:
    def __init__(
        self,
        call_service: CallService,
        mapping_repository: TelephonyCallMappingRepository,
        stream_drain_timeout_seconds: float = STREAM_DRAIN_TIMEOUT_SECONDS,
        call_customer_service: CallCustomerService | None = None,
    ) -> None:
        self._call_service = call_service
        self._mapping_repository = mapping_repository
        self._call_customer_service = call_customer_service
        self._stream_drain_timeout_seconds = stream_drain_timeout_seconds
        # call_id -> set once that call's media stream has no audio left to
        # process. Present only while a stream is open; in-process only.
        self._streams_guard = threading.Lock()
        self._open_streams: dict[str, threading.Event] = {}

    def start_call_from_provider(self, provider: str, event: InboundCallEvent) -> str:
        call_id = f"{provider}-{uuid4()}"
        self._call_service.start_call(call_id)
        self._mapping_repository.save(
            TelephonyCallMapping(
                provider=provider,
                provider_call_id=event.provider_call_id,
                call_id=call_id,
                created_at=time.time(),
            )
        )
        self._record_caller(call_id, event.from_number)
        return call_id

    def _record_caller(self, call_id: str, from_number: str) -> None:
        if self._call_customer_service is None:
            return
        try:
            self._call_customer_service.record_caller(call_id, from_number)
        except Exception:
            # Caller identity is enrichment; the phone call must go ahead.
            logger.exception("Could not record the caller number for call %r", call_id)

    def resolve_call_id(self, provider_call_id: str) -> str | None:
        mapping = self._mapping_repository.get_by_provider_call_id(provider_call_id)
        return mapping.call_id if mapping is not None else None

    # --- Media stream coordination ---

    def stream_opened(self, call_id: str) -> None:
        with self._streams_guard:
            self._open_streams.setdefault(call_id, threading.Event())

    def stream_drained(self, call_id: str) -> None:
        """The call's media stream has processed all its audio (stop,
        disconnect or failure). Releases any terminal status waiting on it."""
        with self._streams_guard:
            drained = self._open_streams.pop(call_id, None)
        if drained is not None:
            drained.set()

    def call_awaiting_stream_drain(self, event: CallStatusEvent) -> str | None:
        """The call_id a terminal event should wait on before completing: set
        only while that call is active and its media stream is still open."""
        if event.status not in _TERMINAL_STATUSES:
            return None
        call_id = self.resolve_call_id(event.provider_call_id)
        if call_id is None:
            return None
        with self._streams_guard:
            if call_id not in self._open_streams:
                return None
        if self._call_service.get_call(call_id).status == ConversationStatus.COMPLETED:
            return None
        return call_id

    def wait_for_stream_drain(self, call_id: str) -> bool:
        """Block until the call's media stream drains or the timeout passes.
        Returns False on timeout. Run it off the event loop."""
        with self._streams_guard:
            drained = self._open_streams.get(call_id)
        if drained is None:
            return True
        return drained.wait(self._stream_drain_timeout_seconds)

    def complete_after_stream_drains(
        self,
        event: CallStatusEvent,
        on_call_completed: Callable[[str], None] | None = None,
    ) -> bool:
        """Let the media stream land its final audio, then complete the call
        through the usual terminal-status path."""
        call_id = self.resolve_call_id(event.provider_call_id)
        if call_id is not None and not self.wait_for_stream_drain(call_id):
            logger.warning(
                "Media stream for call %r did not drain within %.0fs; completing the call anyway",
                call_id,
                self._stream_drain_timeout_seconds,
            )
        return self.handle_status_event(event, on_call_completed)

    # --- Status events ---

    def handle_status_event(
        self,
        event: CallStatusEvent,
        on_call_completed: Callable[[str], None] | None = None,
    ) -> bool:
        """Complete the call on a terminal status. `on_call_completed` is
        invoked only when this event is the one that completed the call, so
        duplicate or late callbacks never trigger post-call processing twice."""
        call_id = self.resolve_call_id(event.provider_call_id)
        if call_id is None:
            return False

        if event.status not in _TERMINAL_STATUSES:
            return True

        conversation = self._call_service.get_call(call_id)
        if conversation.status == ConversationStatus.COMPLETED:
            return True

        end_time = conversation.start_time
        if event.duration_seconds is not None:
            end_time = conversation.start_time + event.duration_seconds
        completion = self._call_service.end_call(
            call_id, max(end_time, conversation.start_time)
        )
        if completion.completed_now and on_call_completed is not None:
            on_call_completed(call_id)
        return True
