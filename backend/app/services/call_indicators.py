"""What a call's screen shows beside the call itself: what the AI is doing
with it right now, and where its record stands.

The AI status is set by whatever is working on the call (the audio stream
while it transcribes, the analysis at each of its steps) and kept in the
LiveStateStore, so every API instance shows the same thing. It runs out by
itself: a worker that dies mid-step never leaves a call "classifying" for
good. Setting it marks the call's live view as changed, so open screens are
told.
"""

import logging
from collections.abc import Callable
from enum import Enum

from app.domain.conversation import Conversation, ConversationStatus
from app.services.live_analysis_store import LiveAnalysisStore
from app.services.live_state_store import LiveStateStore

logger = logging.getLogger(__name__)

# Longer than any one step should take; after it the call reads "listening".
AI_STATUS_TTL_SECONDS = 30.0


class AiStatus(str, Enum):
    # Waiting for speech.
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    CLASSIFYING_COMPLAINT = "classifying_complaint"
    UPDATING_SENTIMENT = "updating_sentiment"
    GENERATING_QUESTION = "generating_question"


class LoggingStatus(str, Enum):
    # The call's audio is being kept as it is spoken.
    RECORDING = "recording"
    # Its recording is stored.
    ARCHIVE_COMPLETE = "archive_complete"
    # Its summary is stored: the call can be reported on and exported.
    EXPORT_READY = "export_ready"


class CallIndicators:
    def __init__(
        self,
        live_state: LiveStateStore,
        is_being_recorded: Callable[[str], bool] | None = None,
        has_recording: Callable[[str], bool] | None = None,
        ttl_seconds: float = AI_STATUS_TTL_SECONDS,
    ) -> None:
        self._live_state = live_state
        self._live_view = LiveAnalysisStore(live_state)
        # call_id -> whether its audio is being kept right now / whether a
        # recording of it is stored. None: this server keeps no recordings.
        self._is_being_recorded = is_being_recorded
        self._has_recording = has_recording
        self._ttl_seconds = ttl_seconds

    # ---- What the AI is doing ----

    def set_ai(self, call_id: str, status: AiStatus) -> None:
        """Never fails the work it describes."""
        try:
            if self._live_state.get_json(_ai_key(call_id)) == status.value:
                return
            self._live_state.set_json(_ai_key(call_id), status.value, self._ttl_seconds)
        except Exception:
            logger.exception("Could not note what the AI is doing on call %r", call_id)
            return
        self._live_view.touch(call_id)

    def ai(self, conversation: Conversation) -> AiStatus | None:
        """None for a call that has ended, or is on hold: nothing is
        listened to then."""
        if conversation.status == ConversationStatus.COMPLETED or conversation.on_hold:
            return None
        try:
            stored = self._live_state.get_json(_ai_key(conversation.call_id))
            return AiStatus.LISTENING if stored is None else AiStatus(stored)
        except Exception:
            logger.exception(
                "Could not read what the AI is doing on call %r", conversation.call_id
            )
            return AiStatus.LISTENING

    # ---- Where the call's record stands ----

    def logging(self, conversation: Conversation, has_summary: bool) -> tuple[LoggingStatus, ...]:
        """Every status that holds now, in the order they come about."""
        call_id = conversation.call_id
        if conversation.status != ConversationStatus.COMPLETED:
            recording = self._ask(self._is_being_recorded, call_id)
            return (LoggingStatus.RECORDING,) if recording else ()
        statuses = []
        if self._ask(self._has_recording, call_id):
            statuses.append(LoggingStatus.ARCHIVE_COMPLETE)
        if has_summary:
            statuses.append(LoggingStatus.EXPORT_READY)
        return tuple(statuses)

    @staticmethod
    def _ask(question: Callable[[str], bool] | None, call_id: str) -> bool:
        if question is None:
            return False
        try:
            return bool(question(call_id))
        except Exception:
            logger.exception("Could not read the recording state of call %r", call_id)
            return False


def _ai_key(call_id: str) -> str:
    return f"ai_status:{call_id}"
