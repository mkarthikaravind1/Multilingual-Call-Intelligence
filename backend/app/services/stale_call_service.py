import logging
import time
from collections.abc import Callable

from app.domain.conversation import Conversation, ConversationStatus
from app.services.call_service import CallService

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100
# A call still active is among the newest ones.
_SCAN_LIMIT = 200


class StaleCallSweeper:
    """Completes phone calls the telephony provider never reported as ended
    (its hangup webhook was missed, e.g. while the backend restarted).
    Without this such a call stays active for ever: no summary, no customer
    message, its complaints never closed out.

    A call is stale once its media stream is closed and nothing more was
    said for idle_seconds. Only calls started by a telephony provider are
    looked at (call_id_prefixes), never manual ones."""

    def __init__(
        self,
        call_service: CallService,
        stream_is_open: Callable[[str], bool],
        complete_call: Callable[[str, float], object],
        *,
        idle_seconds: float,
        call_id_prefixes: tuple[str, ...],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._call_service = call_service
        self._stream_is_open = stream_is_open
        self._complete_call = complete_call
        self._idle_seconds = idle_seconds
        self._call_id_prefixes = call_id_prefixes
        self._clock = clock
        # call_id -> (what had been said, when the call was first seen
        # like that with no open stream). Per instance: after a restart
        # the wait starts again.
        self._idle_since: dict[str, tuple[tuple, float]] = {}

    def run(self) -> int:
        """One sweep. Returns how many calls it completed."""
        now = self._clock()
        completed = 0
        active: set[str] = set()
        for conversation in self._active_calls():
            call_id = conversation.call_id
            active.add(call_id)
            if self._stream_is_open(call_id):
                self._idle_since.pop(call_id, None)
                continue
            said = _what_was_said(conversation)
            seen = self._idle_since.get(call_id)
            if seen is None or seen[0] != said:
                self._idle_since[call_id] = (said, now)
                continue
            idle_since = seen[1]
            if now - idle_since < self._idle_seconds:
                continue
            logger.warning(
                "Completing call %r: no hangup was reported, its stream is closed "
                "and nothing was said for %.0f s",
                call_id,
                now - idle_since,
            )
            try:
                # Ends when it went quiet, not when the sweep got to it.
                self._complete_call(call_id, max(idle_since, conversation.start_time))
            except Exception:
                logger.exception("Completing stale call %r failed", call_id)
                continue
            self._idle_since.pop(call_id, None)
            completed += 1
        for call_id in set(self._idle_since) - active:
            del self._idle_since[call_id]
        return completed

    def _active_calls(self) -> list[Conversation]:
        calls: list[Conversation] = []
        offset = 0
        while offset < _SCAN_LIMIT:
            page = self._call_service.list_calls(min(_PAGE_SIZE, _SCAN_LIMIT - offset), offset)
            if not page:
                break
            offset += len(page)
            calls.extend(
                conversation
                for conversation in page
                if conversation.status is ConversationStatus.ACTIVE
                and conversation.call_id.startswith(self._call_id_prefixes)
            )
        return calls


def _what_was_said(conversation: Conversation) -> tuple:
    """Changes whenever the call gains speech, including a latest line that
    grows as live speech continues it."""
    utterances = conversation.utterances
    return (len(utterances), utterances[-1] if utterances else None)
