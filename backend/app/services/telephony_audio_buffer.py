import io
import wave
from dataclasses import dataclass


class TelephonyAudioBufferError(Exception):
    pass


@dataclass(frozen=True)
class BufferedAudioChunk:
    audio: bytes  # WAV bytes, ready for the existing ASR pipeline
    start_time: float
    end_time: float

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


class TelephonyAudioBuffer:
    """Accumulates raw 16-bit PCM audio for one call's live media stream
    and periodically flushes it into WAV chunks for the existing ASR
    pipeline. Provider-agnostic: works on decoded PCM16 mono audio,
    regardless of which TelephonyProvider produced it, and tracks frame
    sequence numbers to drop duplicate/out-of-order/replayed frames.
    """

    def __init__(
        self,
        sample_rate: int,
        flush_after_seconds: float,
        sample_width_bytes: int = 2,
        channels: int = 1,
    ) -> None:
        if sample_rate <= 0:
            raise TelephonyAudioBufferError("sample_rate must be positive.")
        if flush_after_seconds <= 0:
            raise TelephonyAudioBufferError("flush_after_seconds must be positive.")

        self._sample_rate = sample_rate
        self._sample_width = sample_width_bytes
        self._channels = channels
        self._bytes_per_second = sample_rate * sample_width_bytes * channels
        self._flush_after_bytes = int(flush_after_seconds * self._bytes_per_second)
        self._pending = bytearray()
        self._elapsed_seconds = 0.0
        self._last_sequence: int | None = None

    def accept(self, sequence: int | None, audio: bytes) -> bool:
        """Append a frame's audio unless it's a duplicate or out-of-order
        replay of one already seen. Returns False if the frame was dropped."""
        if sequence is not None and self._last_sequence is not None and sequence <= self._last_sequence:
            return False
        if sequence is not None:
            self._last_sequence = sequence
        if audio:
            self._pending.extend(audio)
        return True

    def should_flush(self) -> bool:
        return len(self._pending) >= self._flush_after_bytes

    def flush(self, *, force: bool = False) -> BufferedAudioChunk | None:
        if not self._pending:
            return None
        if not force and not self.should_flush():
            return None

        data = bytes(self._pending)
        self._pending.clear()

        start_time = self._elapsed_seconds
        duration = len(data) / self._bytes_per_second
        end_time = start_time + duration
        self._elapsed_seconds = end_time

        return BufferedAudioChunk(audio=self._encode_wav(data), start_time=start_time, end_time=end_time)

    def _encode_wav(self, pcm: bytes) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as target:
            target.setnchannels(self._channels)
            target.setsampwidth(self._sample_width)
            target.setframerate(self._sample_rate)
            target.writeframes(pcm)
        return buffer.getvalue()