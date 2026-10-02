"""Live audio is cut at the speaker's pauses, with a time limit."""

import struct

from app.services.telephony_audio_buffer import TelephonyAudioBuffer

RATE = 8000
FRAME = 0.02  # 20 ms frames, as telephony streams send them


def _frame(level: int) -> bytes:
    samples = int(RATE * FRAME)
    # Alternating +/- level: RMS equals level.
    return struct.pack(f"<{samples}h", *([level, -level] * (samples // 2)))


SPEECH = _frame(3000)
QUIET = _frame(50)


def _buffer(**overrides) -> TelephonyAudioBuffer:
    settings = dict(
        sample_rate=RATE,
        flush_after_seconds=8.0,
        pause_seconds=0.6,
        min_speech_seconds=1.5,
        silence_rms=350,
    )
    settings.update(overrides)
    return TelephonyAudioBuffer(**settings)


def _feed(buffer, frame: bytes, seconds: float, sequence: list[int]):
    """Feed frames; return the first chunk flushed, if any."""
    for _ in range(round(seconds / FRAME)):
        sequence[0] += 1
        buffer.accept(sequence[0], frame)
        chunk = buffer.flush()
        if chunk is not None:
            return chunk
    return None


def test_chunk_is_flushed_when_the_speaker_pauses():
    buffer, seq = _buffer(), [0]

    assert _feed(buffer, SPEECH, 2.0, seq) is None
    chunk = _feed(buffer, QUIET, 1.0, seq)

    assert chunk is not None
    # 2 s of speech + the 0.6 s pause, long before the 8 s limit.
    assert abs(chunk.duration - 2.6) < 0.05
    assert chunk.start_time == 0.0


def test_short_bursts_wait_for_enough_speech():
    buffer, seq = _buffer(), [0]

    assert _feed(buffer, SPEECH, 0.5, seq) is None
    assert _feed(buffer, QUIET, 0.8, seq) is None  # only 0.5 s of speech so far
    assert _feed(buffer, SPEECH, 1.2, seq) is None
    chunk = _feed(buffer, QUIET, 1.0, seq)

    assert chunk is not None and chunk.duration > 3.0


def test_continuous_speech_is_cut_at_the_time_limit():
    buffer, seq = _buffer(flush_after_seconds=4.0), [0]

    chunk = _feed(buffer, SPEECH, 10.0, seq)

    assert chunk is not None and abs(chunk.duration - 4.0) < 0.05


def test_silence_alone_never_triggers_an_early_flush():
    buffer, seq = _buffer(flush_after_seconds=4.0), [0]

    chunk = _feed(buffer, QUIET, 10.0, seq)

    # Too quiet to recognise speech: falls back to the time limit, no audio lost.
    assert chunk is not None and abs(chunk.duration - 4.0) < 0.05


def test_chunks_stay_contiguous_after_a_pause_flush():
    buffer, seq = _buffer(), [0]
    _feed(buffer, SPEECH, 2.0, seq)
    first = _feed(buffer, QUIET, 1.0, seq)

    _feed(buffer, SPEECH, 2.0, seq)
    second = _feed(buffer, QUIET, 1.0, seq)

    assert second is not None and second.start_time == first.end_time


def test_pause_detection_can_be_turned_off():
    buffer, seq = _buffer(pause_seconds=0.0, flush_after_seconds=4.0), [0]
    _feed(buffer, SPEECH, 2.0, seq)

    assert _feed(buffer, QUIET, 1.0, seq) is None
