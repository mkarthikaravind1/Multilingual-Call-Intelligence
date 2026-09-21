import io
import math
import wave
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.audio_ingestion_service import IngestedAudio


class AudioChunkingError(Exception):
    pass


@dataclass(frozen=True)
class AudioChunk:
    sequence: int
    start_time: float
    end_time: float
    audio: bytes
    is_final: bool = False

    def __post_init__(self) -> None:
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise AudioChunkingError("sequence must be a non-negative integer.")
        if not self.audio:
            raise AudioChunkingError("chunk audio must not be empty.")
        if self.start_time < 0:
            raise AudioChunkingError("start_time must not be negative.")
        if self.end_time <= self.start_time:
            raise AudioChunkingError("end_time must be after start_time.")

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


def validate_chunk_sequence(chunks: Sequence[AudioChunk]) -> None:
    if not chunks:
        raise AudioChunkingError("chunk sequence must not be empty.")

    last_index = len(chunks) - 1
    previous_end = 0.0
    for index, chunk in enumerate(chunks):
        if chunk.sequence != index:
            raise AudioChunkingError(
                "sequence numbers must be contiguous starting at 0: "
                f"expected {index}, got {chunk.sequence}."
            )
        if chunk.start_time < previous_end:
            raise AudioChunkingError(
                "chunks must be chronological and must not overlap: "
                f"chunk {index} starts at {chunk.start_time}, "
                f"but the previous chunk ends at {previous_end}."
            )
        if chunk.is_final != (index == last_index):
            raise AudioChunkingError("only the last chunk may be marked final.")
        previous_end = chunk.end_time


class AudioChunkingService:
    def __init__(self, chunk_duration_seconds: float) -> None:
        if (
            isinstance(chunk_duration_seconds, bool)
            or not isinstance(chunk_duration_seconds, (int, float))
            or not math.isfinite(chunk_duration_seconds)
            or chunk_duration_seconds <= 0
        ):
            raise AudioChunkingError(
                "chunk_duration_seconds must be a positive, finite number."
            )
        self._chunk_duration_seconds = float(chunk_duration_seconds)

    def chunk(self, ingested: IngestedAudio) -> list[AudioChunk]:
        if not ingested.audio:
            raise AudioChunkingError("audio must not be empty.")

        try:
            chunks = self._split(ingested.audio)
        except (wave.Error, EOFError) as exc:
            raise AudioChunkingError("audio is not a valid WAV file.") from exc

        validate_chunk_sequence(chunks)
        return chunks

    def _split(self, audio: bytes) -> list[AudioChunk]:
        with wave.open(io.BytesIO(audio), "rb") as source:
            sample_rate = source.getframerate()
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            total_frames = source.getnframes()

            if sample_rate <= 0:
                raise AudioChunkingError("audio has an invalid sample rate.")
            if total_frames == 0:
                raise AudioChunkingError("audio contains no frames.")

            frames_per_chunk = round(self._chunk_duration_seconds * sample_rate)
            if frames_per_chunk < 1:
                raise AudioChunkingError(
                    "chunk_duration_seconds is too small for the audio sample rate."
                )

            frame_size = channels * sample_width
            chunks: list[AudioChunk] = []
            start_frame = 0
            while start_frame < total_frames:
                data = source.readframes(frames_per_chunk)
                frame_count = len(data) // frame_size
                if frame_count == 0:
                    raise AudioChunkingError("audio data is truncated.")

                end_frame = start_frame + frame_count
                chunks.append(
                    AudioChunk(
                        sequence=len(chunks),
                        start_time=start_frame / sample_rate,
                        end_time=end_frame / sample_rate,
                        audio=self._encode(
                            data[: frame_count * frame_size],
                            channels,
                            sample_width,
                            sample_rate,
                        ),
                        is_final=end_frame >= total_frames,
                    )
                )
                start_frame = end_frame
            return chunks

    @staticmethod
    def _encode(
        frames: bytes, channels: int, sample_width: int, sample_rate: int
    ) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as target:
            target.setnchannels(channels)
            target.setsampwidth(sample_width)
            target.setframerate(sample_rate)
            target.writeframes(frames)
        return buffer.getvalue()