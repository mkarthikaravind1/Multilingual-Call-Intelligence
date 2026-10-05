import audioop
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
    # The chunk ends in a pause (pause_seconds of silence), whether that
    # pause triggered the flush or the time limit was reached during it.
    ends_on_pause: bool = False
    # The chunk's speech carries straight on from the previous chunk's
    # speech: no pause in between, so the time limit cut a sentence.
    continues_previous: bool = False
    # Any audio above the silence level. Always True with pause detection
    # off (nothing is measured then).
    has_speech: bool = True

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


class TelephonyAudioBuffer:
    """Accumulates raw 16-bit PCM audio for one call's live media stream
    and flushes it into WAV chunks for the existing ASR pipeline.
    Provider-agnostic: works on decoded PCM16 mono audio, regardless of
    which TelephonyProvider produced it, and tracks frame sequence numbers
    to drop duplicate/out-of-order/replayed frames.

    A chunk is flushed when the speaker pauses (at least min_speech_seconds
    of speech followed by pause_seconds below silence_rms), so the
    transcript follows the speech closely and words are not cut in half;
    flush_after_seconds is the upper limit. pause_seconds=0 turns pause
    detection off (fixed-length chunks). Audio is never dropped: if no
    pause is recognised, chunks simply reach the upper limit.

    Each chunk records whether it ends on a pause and whether its speech
    continues the previous chunk's (a pause can straddle a time-limit cut),
    so speech cut by the time limit can be joined back into one utterance.
    With pause detection off, chunks never continue one another.
    """

    def __init__(
        self,
        sample_rate: int,
        flush_after_seconds: float,
        sample_width_bytes: int = 2,
        channels: int = 1,
        pause_seconds: float = 0.0,
        min_speech_seconds: float = 1.0,
        silence_rms: int = 350,
    ) -> None:
        if sample_rate <= 0:
            raise TelephonyAudioBufferError("sample_rate must be positive.")
        if flush_after_seconds <= 0:
            raise TelephonyAudioBufferError("flush_after_seconds must be positive.")
        if pause_seconds < 0 or min_speech_seconds < 0 or silence_rms < 0:
            raise TelephonyAudioBufferError("Pause detection settings must not be negative.")

        self._sample_rate = sample_rate
        self._sample_width = sample_width_bytes
        self._channels = channels
        self._bytes_per_second = sample_rate * sample_width_bytes * channels
        self._flush_after_bytes = int(flush_after_seconds * self._bytes_per_second)
        self._pending = bytearray()
        self._elapsed_seconds = 0.0
        self._last_sequence: int | None = None
        self._pause_bytes = int(pause_seconds * self._bytes_per_second)
        self._min_speech_bytes = int(min_speech_seconds * self._bytes_per_second)
        self._silence_rms = silence_rms
        self._speech_bytes = 0
        self._trailing_silence_bytes = 0
        # Silence since the last speech, across flushes; the stream starts
        # as if after a pause.
        self._silence_run_bytes = self._pause_bytes
        self._chunk_has_speech = False
        self._continues_previous = False

    def accept(self, sequence: int | None, audio: bytes) -> bool:
        """Append a frame's audio unless it's a duplicate or out-of-order
        replay of one already seen. Returns False if the frame was dropped."""
        if sequence is not None and self._last_sequence is not None and sequence <= self._last_sequence:
            return False
        if sequence is not None:
            self._last_sequence = sequence
        if audio:
            self._pending.extend(audio)
            self._track_speech(audio)
        return True

    def should_flush(self) -> bool:
        if len(self._pending) >= self._flush_after_bytes:
            return True
        return (
            self._pause_bytes > 0
            and self._chunk_has_speech
            and self._speech_bytes >= self._min_speech_bytes
            and self._trailing_silence_bytes >= self._pause_bytes
        )

    def _track_speech(self, audio: bytes) -> None:
        if not self._pause_bytes:
            return
        try:
            loud = audioop.rms(audio, self._sample_width) >= self._silence_rms
        except audioop.error:
            return  # odd-sized frame: leave the counters as they are
        if loud:
            if not self._chunk_has_speech:
                self._chunk_has_speech = True
                self._continues_previous = self._silence_run_bytes < self._pause_bytes
            self._speech_bytes += len(audio)
            self._trailing_silence_bytes = 0
            self._silence_run_bytes = 0
        else:
            self._trailing_silence_bytes += len(audio)
            self._silence_run_bytes += len(audio)

    def flush(self, *, force: bool = False) -> BufferedAudioChunk | None:
        if not self._pending:
            return None
        if not force and not self.should_flush():
            return None

        data = bytes(self._pending)
        ends_on_pause = self._pause_bytes > 0 and self._trailing_silence_bytes >= self._pause_bytes
        continues_previous = self._continues_previous
        has_speech = self._chunk_has_speech or not self._pause_bytes
        self._pending.clear()
        if ends_on_pause or not self._pause_bytes:
            self._speech_bytes = 0
        # else: the time limit cut a sentence, so its speech so far still
        # counts and the pause that ends it flushes at once (min_speech
        # counts the sentence, not just the part after the cut).
        self._trailing_silence_bytes = 0
        self._chunk_has_speech = False
        self._continues_previous = False

        start_time = self._elapsed_seconds
        duration = len(data) / self._bytes_per_second
        end_time = start_time + duration
        self._elapsed_seconds = end_time

        return BufferedAudioChunk(
            audio=self._encode_wav(data),
            start_time=start_time,
            end_time=end_time,
            ends_on_pause=ends_on_pause,
            continues_previous=continues_previous,
            has_speech=has_speech,
        )

    def _encode_wav(self, pcm: bytes) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as target:
            target.setnchannels(self._channels)
            target.setsampwidth(self._sample_width)
            target.setframerate(self._sample_rate)
            target.writeframes(pcm)
        return buffer.getvalue()