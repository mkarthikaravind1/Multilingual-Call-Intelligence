from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

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
        self, call_id: str, audio: bytes, start_offset: float = 0.0
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
class _StreamState:
    processor: ChunkAudioProcessor
    next_sequence: int = 0
    last_end_time: float = 0.0
    completed: bool = False


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
        if state is not None and state.completed:
            raise StreamCompletedError(
                f"Stream for call {call_id!r} is already complete."
            )

        expected = state.next_sequence if state is not None else 0
        if chunk.sequence < expected:
            raise DuplicateChunkError(
                f"Chunk {chunk.sequence} for call {call_id!r} was already "
                f"processed; expected sequence {expected}."
            )
        if chunk.sequence > expected:
            raise OutOfOrderChunkError(
                f"Chunk {chunk.sequence} for call {call_id!r} arrived out of "
                f"order; expected sequence {expected}."
            )
        if state is not None and chunk.start_time < state.last_end_time:
            raise OutOfOrderChunkError(
                f"Chunk {chunk.sequence} for call {call_id!r} starts at "
                f"{chunk.start_time}, before the previous chunk ends at "
                f"{state.last_end_time}."
            )

        processor = (
            state.processor if state is not None else self._processor_factory(call_id)
        )
        analysis = processor.process_audio(
            call_id, chunk.audio, start_offset=chunk.start_time
        )

        if state is None:
            state = _StreamState(processor)
            self._streams[call_id] = state
        state.next_sequence = chunk.sequence + 1
        state.last_end_time = chunk.end_time
        state.completed = chunk.is_final

        return ChunkProcessingResult(
            call_id=call_id,
            sequence=chunk.sequence,
            start_time=chunk.start_time,
            end_time=chunk.end_time,
            is_final=chunk.is_final,
            analysis=analysis,
        )