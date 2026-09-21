import io
import wave
from dataclasses import dataclass
from pathlib import Path


class AudioIngestionError(Exception):
    pass


@dataclass(frozen=True)
class AudioMetadata:
    sample_rate: int
    channels: int
    sample_width_bytes: int
    frame_count: int
    duration_seconds: float
    size_bytes: int


@dataclass(frozen=True)
class IngestedAudio:
    audio: bytes
    metadata: AudioMetadata


class AudioIngestionService:
    def load_wav(self, path: str | Path) -> IngestedAudio:
        file_path = Path(path)
        if not file_path.is_file():
            raise AudioIngestionError(f"Audio file not found: {file_path}")

        try:
            audio = file_path.read_bytes()
        except OSError as exc:
            raise AudioIngestionError(
                f"Audio file could not be read: {file_path}"
            ) from exc

        if not audio:
            raise AudioIngestionError(f"Audio file is empty: {file_path}")

        return IngestedAudio(audio=audio, metadata=self._read_metadata(audio))

    @staticmethod
    def _read_metadata(audio: bytes) -> AudioMetadata:
        try:
            with wave.open(io.BytesIO(audio), "rb") as wav:
                sample_rate = wav.getframerate()
                channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                frame_count = wav.getnframes()
        except (wave.Error, EOFError) as exc:
            raise AudioIngestionError("File is not a valid WAV audio file.") from exc

        if sample_rate <= 0:
            raise AudioIngestionError("WAV file has an invalid sample rate.")
        if frame_count == 0:
            raise AudioIngestionError("WAV file contains no audio frames.")

        return AudioMetadata(
            sample_rate=sample_rate,
            channels=channels,
            sample_width_bytes=sample_width,
            frame_count=frame_count,
            duration_seconds=frame_count / sample_rate,
            size_bytes=len(audio),
        )