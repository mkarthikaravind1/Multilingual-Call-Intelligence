import logging
import threading
import time
from collections.abc import Callable
from uuid import uuid4

from app.domain.conversation import ConversationStatus
from app.domain.telephony_call_mapping import TelephonyCallMapping
from app.services.call_customer_service import CallCustomerService
from app.services.call_service import CallService
from app.services.live_state_store import InMemoryLiveStateStore, LiveStateStore
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

# How long a stream stays marked open in the shared store if its instance
# dies without cleaning up. Longer than any real call.
STREAM_STATE_TTL_SECONDS = 6 * 60 * 60
# How often a status webhook on another instance re-checks the stream.
_SHARED_DRAIN_POLL_SECONDS = 0.25


def _stream_key(call_id: str) -> str:
    return f"stream:{call_id}"


class TelephonyCallService:
    def __init__(
        self,
        call_service: CallService,
        mapping_repository: TelephonyCallMappingRepository,
        stream_drain_timeout_seconds: float = STREAM_DRAIN_TIMEOUT_SECONDS,
        call_customer_service: CallCustomerService | None = None,
        live_state: LiveStateStore | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._call_service = call_service
        self._mapping_repository = mapping_repository
        self._call_customer_service = call_customer_service
        self._stream_drain_timeout_seconds = stream_drain_timeout_seconds
        # call_id -> set once that call's media stream has no audio left to
        # process. Present only while a stream is open on this instance; the
        # shared store tells other instances (e.g. the one receiving the
        # status webhook) that the stream is still open.
        self._streams_guard = threading.Lock()
        self._open_streams: dict[str, threading.Event] = {}
        self._live_state = live_state or InMemoryLiveStateStore()
        # Calls start and end on the wall clock (Unix seconds), like manual
        # calls, so a call's duration is right whichever way it is ended.
        self._clock = clock

    def start_call_from_provider(self, provider: str, event: InboundCallEvent) -> str:
        call_id = f"{provider}-{uuid4()}"
        self._call_service.start_call(call_id, self._clock())
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
        try:
            self._live_state.set_json(
                _stream_key(call_id), True, ttl_seconds=STREAM_STATE_TTL_SECONDS
            )
        except Exception:
            logger.exception("Could not share the open stream of call %r", call_id)

    def stream_drained(self, call_id: str) -> None:
        """The call's media stream has processed all its audio (stop,
        disconnect or failure). Releases any terminal status waiting on it."""
        with self._streams_guard:
            drained = self._open_streams.pop(call_id, None)
        try:
            self._live_state.delete(_stream_key(call_id))
        except Exception:
            logger.exception("Could not share the drained stream of call %r", call_id)
        if drained is not None:
            drained.set()

    def _stream_open_elsewhere(self, call_id: str) -> bool:
        try:
            return self._live_state.get_json(_stream_key(call_id)) is not None
        except Exception:
            logger.exception("Could not read the stream state of call %r", call_id)
            return False

    def call_awaiting_stream_drain(self, event: CallStatusEvent) -> str | None:
        """The call_id a terminal event should wait on before completing: set
        only while that call is active and its media stream is still open."""
        if event.status not in _TERMINAL_STATUSES:
            return None
        call_id = self.resolve_call_id(event.provider_call_id)
        if call_id is None:
            return None
        with self._streams_guard:
            open_here = call_id in self._open_streams
        if not open_here and not self._stream_open_elsewhere(call_id):
            return None
        if self._call_service.get_call(call_id).status == ConversationStatus.COMPLETED:
            return None
        return call_id

    def wait_for_stream_drain(self, call_id: str) -> bool:
        """Block until the call's media stream drains or the timeout passes.
        Returns False on timeout. Run it off the event loop."""
        with self._streams_guard:
            drained = self._open_streams.get(call_id)
        if drained is not None:
            return drained.wait(self._stream_drain_timeout_seconds)

        # The stream is on another instance: watch the shared store.
        deadline = time.monotonic() + self._stream_drain_timeout_seconds
        while self._stream_open_elsewhere(call_id):
            if time.monotonic() >= deadline:
                return False
            time.sleep(_SHARED_DRAIN_POLL_SECONDS)
        return True

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

        if event.duration_seconds is not None:
            end_time = conversation.start_time + event.duration_seconds
        else:
            end_time = self._clock()
        completion = self._call_service.end_call(
            call_id, max(end_time, conversation.start_time)
        )
        if completion.completed_now and on_call_completed is not None:
            on_call_completed(call_id)
        return True
