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


# --- Flush reason and continuity (live utterances grow across chunks) ---


def test_a_three_second_limit_leaves_room_for_the_pause_detector():
    # min speech 1.5 s + pause 0.6 s = 2.1 s, inside the 3.0 s limit.
    buffer, seq = _buffer(flush_after_seconds=3.0), [0]

    assert _feed(buffer, SPEECH, 1.6, seq) is None
    chunk = _feed(buffer, QUIET, 1.0, seq)

    assert chunk is not None and abs(chunk.duration - 2.2) < 0.05
    assert chunk.ends_on_pause
    assert not chunk.continues_previous  # first speech of the stream


def test_continuous_speech_cut_by_the_limit_continues_across_chunks():
    buffer, seq = _buffer(flush_after_seconds=3.0), [0]

    first = _feed(buffer, SPEECH, 10.0, seq)
    second = _feed(buffer, SPEECH, 10.0, seq)

    assert abs(first.duration - 3.0) < 0.05 and abs(second.duration - 3.0) < 0.05
    # The limit is not a pause: the speaker is still mid-sentence.
    assert not first.ends_on_pause and not second.ends_on_pause
    assert not first.continues_previous
    assert second.continues_previous


def test_speech_after_a_pause_flush_does_not_continue():
    buffer, seq = _buffer(flush_after_seconds=3.0), [0]
    _feed(buffer, SPEECH, 2.0, seq)
    first = _feed(buffer, QUIET, 1.0, seq)

    _feed(buffer, QUIET, 0.4, seq)
    second = _feed(buffer, SPEECH, 10.0, seq)

    assert first.ends_on_pause
    assert second is not None and not second.continues_previous


def test_a_pause_straddling_a_limit_cut_still_separates_the_speech():
    buffer, seq = _buffer(flush_after_seconds=3.0), [0]

    # Speech stops 0.3 s before the limit: too little silence to flush on
    # the pause, so the limit cuts the chunk.
    first = _feed(buffer, SPEECH, 2.7, seq) or _feed(buffer, QUIET, 0.3, seq)
    assert first is not None and not first.ends_on_pause

    # The pause carries on into the next chunk before new speech starts.
    _feed(buffer, QUIET, 0.5, seq)
    second = _feed(buffer, SPEECH, 10.0, seq)

    assert second is not None and not second.continues_previous


def test_a_brief_dip_between_words_is_not_a_pause():
    buffer, seq = _buffer(flush_after_seconds=3.0), [0]

    first = _feed(buffer, SPEECH, 2.8, seq) or _feed(buffer, QUIET, 0.2, seq)
    _feed(buffer, QUIET, 0.2, seq)
    second = _feed(buffer, SPEECH, 10.0, seq)

    assert first is not None and not first.ends_on_pause
    assert second is not None and second.continues_previous


def test_a_silent_chunk_ends_on_a_pause():
    buffer, seq = _buffer(flush_after_seconds=3.0), [0]

    chunk = _feed(buffer, QUIET, 10.0, seq)

    assert chunk is not None and chunk.ends_on_pause and not chunk.continues_previous


def test_without_pause_detection_chunks_never_continue():
    buffer, seq = _buffer(pause_seconds=0.0, flush_after_seconds=3.0), [0]

    first = _feed(buffer, SPEECH, 10.0, seq)
    second = _feed(buffer, SPEECH, 10.0, seq)

    assert not first.continues_previous and not second.continues_previous
    assert not first.ends_on_pause and not second.ends_on_pause


def test_the_end_of_a_cut_sentence_is_flushed_at_its_pause():
    buffer, seq = _buffer(flush_after_seconds=3.0), [0]
    first = _feed(buffer, SPEECH, 10.0, seq)  # cut by the limit at 3 s

    # 0.5 s more of the sentence, then a pause: under min_speech on its own,
    # but the sentence has been going for 3.5 s.
    assert _feed(buffer, SPEECH, 0.5, seq) is None
    tail = _feed(buffer, QUIET, 1.0, seq)

    assert not first.ends_on_pause
    assert tail is not None and abs(tail.duration - 1.1) < 0.05
    assert tail.ends_on_pause and tail.continues_previous


def test_a_pause_straddling_a_cut_does_not_flush_bare_silence():
    buffer, seq = _buffer(flush_after_seconds=3.0), [0]
    _feed(buffer, SPEECH, 2.8, seq) or _feed(buffer, QUIET, 0.2, seq)

    assert _feed(buffer, QUIET, 1.0, seq) is None  # no speech yet: keep waiting
