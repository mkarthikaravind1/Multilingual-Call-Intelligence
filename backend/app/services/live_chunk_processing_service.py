import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Protocol

from app.domain.utterance import SpeakerRole
from app.services.audio_chunking_service import AudioChunk
from app.services.call_workflow_service import CallAnalysisResult

logger = logging.getLogger(__name__)


class LiveChunkProcessingError(Exception):
    pass


class ChunkOrderError(LiveChunkProcessingError):
    pass


class DuplicateChunkError(ChunkOrderError):
    pass


class OutOfOrderChunkError(ChunkOrderError):
    pass


class StreamCompletedError(LiveChunkProcessingError):
    pass


class ChunkAudioProcessor(Protocol):
    def process_audio(
        self,
        call_id: str,
        audio: bytes,
        start_offset: float = 0.0,
        *,
        continues_previous: bool = False,
        ends_utterance: bool = True,
        track: str | None = None,
        speaker_role: SpeakerRole | None = None,
    ) -> CallAnalysisResult: ...


@dataclass(frozen=True)
class ChunkProcessingResult:
    call_id: str
    sequence: int
    start_time: float
    end_time: float
    is_final: bool
    analysis: CallAnalysisResult


# A call's state is forgotten after this long without audio (the stream
# ended, or the call was abandoned). Matches how long speaker roles are kept.
IDLE_STREAM_SECONDS = 6 * 60 * 60
# How often process_chunk looks for idle calls to forget.
_SWEEP_SECONDS = 60.0


@dataclass
class _TrackState:
    next_sequence: int = 0
    last_end_time: float = 0.0
    completed: bool = False
    # A restarted stream numbers its chunks from 0 again; added to them.
    sequence_base: int = 0


@dataclass
class _StreamState:
    # Built lazily so a failed build is retried on the next chunk. One per
    # call, shared by its tracks, so their utterances join one transcript.
    processor: ChunkAudioProcessor | None = None
    # Sequence numbers and times run separately for each track (None: a
    # single mixed stream).
    tracks: dict[str | None, _TrackState] = field(default_factory=dict)
    # A restarted stream starts its times at 0 again; added to them so the
    # call's timeline keeps going forward.
    time_base: float = 0.0
    last_used: float = 0.0

    @property
    def completed(self) -> bool:
        return bool(self.tracks) and all(t.completed for t in self.tracks.values())


class LiveChunkProcessingService:
    """Feeds each call's audio chunks, in order, to that call's processor.

    A call's stream may stop and start again (a provider-side restart, or a
    reconnect after a dropped socket): call stream_started() before its
    chunks, and its sequence numbers and times carry on from the call's
    previous stream. A call idle for idle_seconds is forgotten, and
    on_forget(call_id) lets per-call state elsewhere go too.
    """

    def __init__(
        self,
        processor_factory: Callable[[str], ChunkAudioProcessor],
        *,
        on_forget: Callable[[str], None] | None = None,
        idle_seconds: float = IDLE_STREAM_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._processor_factory = processor_factory
        self._streams: dict[str, _StreamState] = {}
        self._on_forget = on_forget
        self._idle_seconds = idle_seconds
        self._clock = clock
        # Guards adding and forgetting calls; one call's chunks are processed
        # in order by a single worker.
        self._guard = threading.Lock()
        self._next_sweep = 0.0

    def is_completed(self, call_id: str) -> bool:
        state = self._streams.get(call_id)
        return state is not None and state.completed

    def stream_started(self, call_id: str) -> None:
        """A (new) media stream for the call begins; its chunks number from
        0 and its times from 0. Nothing to do for a call not seen yet."""
        state = self._streams.get(call_id)
        if state is None or not state.tracks:
            return
        state.time_base = max(track.last_end_time for track in state.tracks.values())
        for track in state.tracks.values():
            track.sequence_base = track.next_sequence
            track.completed = False

    def process_chunk(self, call_id: str, chunk: AudioChunk) -> ChunkProcessingResult:
        if not isinstance(call_id, str) or not call_id.strip():
            raise LiveChunkProcessingError("call_id must not be empty.")
        if not isinstance(chunk, AudioChunk):
            raise LiveChunkProcessingError("chunk must be an AudioChunk.")

        self._forget_idle_calls()
        state = self._streams.get(call_id)
        track_state = state.tracks.get(chunk.track) if state is not None else None
        if state is not None and state.time_base:
            chunk = replace(
                chunk,
                start_time=chunk.start_time + state.time_base,
                end_time=chunk.end_time + state.time_base,
            )
        if track_state is not None and track_state.sequence_base:
            chunk = replace(chunk, sequence=chunk.sequence + track_state.sequence_base)
        if track_state is not None and track_state.completed:
            raise StreamCompletedError(
                f"Stream for call {call_id!r} is already complete."
            )

        label = _label(call_id, chunk.track)
        expected = track_state.next_sequence if track_state is not None else 0
        if chunk.sequence < expected:
            raise DuplicateChunkError(
                f"Chunk {chunk.sequence} for {label} was already "
                f"processed; expected sequence {expected}."
            )
        if chunk.sequence > expected:
            raise OutOfOrderChunkError(
                f"Chunk {chunk.sequence} for {label} arrived out of "
                f"order; expected sequence {expected}."
            )
        if track_state is not None and chunk.start_time < track_state.last_end_time:
            raise OutOfOrderChunkError(
                f"Chunk {chunk.sequence} for {label} starts at "
                f"{chunk.start_time}, before the previous chunk ends at "
                f"{track_state.last_end_time}."
            )

        if state is None:
            state = _StreamState()
            with self._guard:
                self._streams[call_id] = state
        if track_state is None:
            track_state = _TrackState()
            state.tracks[chunk.track] = track_state
        state.last_used = self._clock()

        # A chunk that passed the order checks is consumed even if processing
        # fails: the stream never resends audio, so holding the sequence back
        # would reject every later chunk of the call as out of order.
        try:
            if state.processor is None:
                state.processor = self._processor_factory(call_id)
            # Speech the time limit cut mid-sentence extends the current
            # utterance; a pause (or the end of the stream) closes it.
            analysis = state.processor.process_audio(
                call_id,
                chunk.audio,
                start_offset=chunk.start_time,
                continues_previous=chunk.continues_previous,
                ends_utterance=chunk.ends_on_pause or chunk.is_final,
                track=chunk.track,
                speaker_role=chunk.speaker_role,
            )
        finally:
            track_state.next_sequence = chunk.sequence + 1
            track_state.last_end_time = chunk.end_time
            track_state.completed = chunk.is_final

        return ChunkProcessingResult(
            call_id=call_id,
            sequence=chunk.sequence,
            start_time=chunk.start_time,
            end_time=chunk.end_time,
            is_final=chunk.is_final,
            analysis=analysis,
        )


    def _forget_idle_calls(self) -> None:
        now = self._clock()
        if now < self._next_sweep:
            return
        with self._guard:
            if now < self._next_sweep:
                return
            self._next_sweep = now + _SWEEP_SECONDS
            idle = [
                call_id
                for call_id, state in self._streams.items()
                if now - state.last_used >= self._idle_seconds
            ]
            for call_id in idle:
                del self._streams[call_id]
        for call_id in idle:
            if self._on_forget is not None:
                try:
                    self._on_forget(call_id)
                except Exception:
                    logger.exception("Could not forget the live state of call %r", call_id)


def _label(call_id: str, track: str | None) -> str:
    return f"call {call_id!r}" if track is None else f"call {call_id!r} ({track} track)"
