from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.domain.utterance import SpeakerRole
from app.services.audio_chunking_service import AudioChunk
from app.services.call_workflow_service import CallAnalysisResult


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


@dataclass
class _TrackState:
    next_sequence: int = 0
    last_end_time: float = 0.0
    completed: bool = False


@dataclass
class _StreamState:
    # Built lazily so a failed build is retried on the next chunk. One per
    # call, shared by its tracks, so their utterances join one transcript.
    processor: ChunkAudioProcessor | None = None
    # Sequence numbers and times run separately for each track (None: a
    # single mixed stream).
    tracks: dict[str | None, _TrackState] = field(default_factory=dict)

    @property
    def completed(self) -> bool:
        return bool(self.tracks) and all(t.completed for t in self.tracks.values())


class LiveChunkProcessingService:
    def __init__(
        self, processor_factory: Callable[[str], ChunkAudioProcessor]
    ) -> None:
        self._processor_factory = processor_factory
        self._streams: dict[str, _StreamState] = {}

    def is_completed(self, call_id: str) -> bool:
        state = self._streams.get(call_id)
        return state is not None and state.completed

    def process_chunk(self, call_id: str, chunk: AudioChunk) -> ChunkProcessingResult:
        if not isinstance(call_id, str) or not call_id.strip():
            raise LiveChunkProcessingError("call_id must not be empty.")
        if not isinstance(chunk, AudioChunk):
            raise LiveChunkProcessingError("chunk must be an AudioChunk.")

        state = self._streams.get(call_id)
        track_state = state.tracks.get(chunk.track) if state is not None else None
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
            self._streams[call_id] = state
        if track_state is None:
            track_state = _TrackState()
            state.tracks[chunk.track] = track_state

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


def _label(call_id: str, track: str | None) -> str:
    return f"call {call_id!r}" if track is None else f"call {call_id!r} ({track} track)"
