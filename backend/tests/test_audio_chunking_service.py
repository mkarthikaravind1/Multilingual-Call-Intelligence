import io
import struct
import wave

import pytest

from app.services.audio_chunking_service import (
    AudioChunk,
    AudioChunkingError,
    AudioChunkingService,
    validate_chunk_sequence,
)
from app.services.audio_ingestion_service import AudioMetadata, IngestedAudio

SAMPLE_RATE = 1000


def make_wav(frames: int, channels: int = 1, sample_rate: int = SAMPLE_RATE) -> bytes:
    samples = frames * channels
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(struct.pack(f"<{samples}h", *range(samples)))
    return buffer.getvalue()


def wrap(
    audio: bytes,
    frames: int = 1,
    channels: int = 1,
    sample_rate: int = SAMPLE_RATE,
) -> IngestedAudio:
    return IngestedAudio(
        audio=audio,
        metadata=AudioMetadata(
            sample_rate=sample_rate,
            channels=channels,
            sample_width_bytes=2,
            frame_count=frames,
            duration_seconds=frames / sample_rate,
            size_bytes=len(audio),
        ),
    )


def make_ingested(frames: int, channels: int = 1) -> IngestedAudio:
    return wrap(make_wav(frames, channels), frames, channels)


def read_wav(audio: bytes) -> tuple[int, int, int, int, bytes]:
    with wave.open(io.BytesIO(audio), "rb") as wav:
        return (
            wav.getnchannels(),
            wav.getsampwidth(),
            wav.getframerate(),
            wav.getnframes(),
            wav.readframes(wav.getnframes()),
        )


def make_chunk(
    sequence: int = 0,
    start: float = 0.0,
    end: float = 1.0,
    final: bool = False,
) -> AudioChunk:
    return AudioChunk(
        sequence=sequence,
        start_time=start,
        end_time=end,
        audio=b"audio",
        is_final=final,
    )


def test_exact_multiple_produces_full_ordered_chunks():
    chunks = AudioChunkingService(1.0).chunk(make_ingested(3000))

    assert [c.sequence for c in chunks] == [0, 1, 2]
    assert [(c.start_time, c.end_time) for c in chunks] == [
        (0.0, 1.0),
        (1.0, 2.0),
        (2.0, 3.0),
    ]
    assert [c.is_final for c in chunks] == [False, False, True]
    assert all(c.duration == pytest.approx(1.0) for c in chunks)


def test_final_partial_chunk_is_shorter_and_marked_final():
    chunks = AudioChunkingService(1.0).chunk(make_ingested(2500))

    assert len(chunks) == 3
    final = chunks[-1]
    assert final.is_final is True
    assert final.start_time == pytest.approx(2.0)
    assert final.end_time == pytest.approx(2.5)
    assert final.duration == pytest.approx(0.5)
    assert read_wav(final.audio)[3] == 500


def test_audio_shorter_than_chunk_size_yields_single_final_chunk():
    chunks = AudioChunkingService(5.0).chunk(make_ingested(500))

    assert len(chunks) == 1
    assert chunks[0].sequence == 0
    assert chunks[0].start_time == 0.0
    assert chunks[0].end_time == pytest.approx(0.5)
    assert chunks[0].is_final is True


def test_each_chunk_is_a_valid_wav_with_original_format():
    chunks = AudioChunkingService(1.0).chunk(make_ingested(1500, channels=2))

    assert len(chunks) == 2
    for chunk in chunks:
        channels, sample_width, sample_rate, _, _ = read_wav(chunk.audio)
        assert (channels, sample_width, sample_rate) == (2, 2, SAMPLE_RATE)


def test_chunks_reassemble_to_original_audio():
    ingested = make_ingested(2500)

    chunks = AudioChunkingService(1.0).chunk(ingested)

    combined = b"".join(read_wav(c.audio)[4] for c in chunks)
    assert combined == read_wav(ingested.audio)[4]


def test_chunking_is_repeatable():
    service = AudioChunkingService(1.0)
    ingested = make_ingested(2500)

    assert service.chunk(ingested) == service.chunk(ingested)


@pytest.mark.parametrize(
    "size", [0, -1.0, float("nan"), float("inf"), True, "5", None]
)
def test_invalid_chunk_duration_is_rejected(size):
    with pytest.raises(AudioChunkingError, match="chunk_duration_seconds"):
        AudioChunkingService(size)


def test_chunk_duration_too_small_for_sample_rate_is_rejected():
    with pytest.raises(AudioChunkingError, match="too small"):
        AudioChunkingService(0.0001).chunk(make_ingested(1000))


def test_empty_audio_is_rejected():
    with pytest.raises(AudioChunkingError, match="must not be empty"):
        AudioChunkingService(1.0).chunk(wrap(b""))


def test_non_wav_audio_is_rejected():
    with pytest.raises(AudioChunkingError, match="valid WAV"):
        AudioChunkingService(1.0).chunk(wrap(b"not a wav file"))


def test_wav_without_frames_is_rejected():
    with pytest.raises(AudioChunkingError, match="no frames"):
        AudioChunkingService(1.0).chunk(wrap(make_wav(0), frames=0))


def test_truncated_wav_data_is_rejected():
    truncated = make_wav(3000)[:-2500]

    with pytest.raises(AudioChunkingError, match="truncated"):
        AudioChunkingService(1.0).chunk(wrap(truncated, frames=3000))


def test_valid_sequence_passes_validation():
    validate_chunk_sequence(
        [make_chunk(0, 0.0, 1.0), make_chunk(1, 1.0, 1.5, final=True)]
    )


def test_empty_sequence_is_rejected():
    with pytest.raises(AudioChunkingError, match="must not be empty"):
        validate_chunk_sequence([])


def test_non_contiguous_sequence_numbers_are_rejected():
    chunks = [make_chunk(0, 0.0, 1.0), make_chunk(2, 1.0, 2.0, final=True)]

    with pytest.raises(AudioChunkingError, match="contiguous"):
        validate_chunk_sequence(chunks)


def test_overlapping_chunks_are_rejected():
    chunks = [make_chunk(0, 0.0, 1.0), make_chunk(1, 0.5, 1.5, final=True)]

    with pytest.raises(AudioChunkingError, match="overlap"):
        validate_chunk_sequence(chunks)


def test_out_of_order_chunks_are_rejected():
    chunks = [make_chunk(0, 1.0, 2.0), make_chunk(1, 0.0, 1.0, final=True)]

    with pytest.raises(AudioChunkingError, match="chronological"):
        validate_chunk_sequence(chunks)


def test_missing_final_marker_is_rejected():
    with pytest.raises(AudioChunkingError, match="final"):
        validate_chunk_sequence([make_chunk(0, 0.0, 1.0)])


def test_early_final_marker_is_rejected():
    chunks = [
        make_chunk(0, 0.0, 1.0, final=True),
        make_chunk(1, 1.0, 2.0, final=True),
    ]

    with pytest.raises(AudioChunkingError, match="final"):
        validate_chunk_sequence(chunks)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sequence": -1},
        {"sequence": True},
        {"audio": b""},
        {"start_time": -0.1},
        {"start_time": 1.0, "end_time": 1.0},
        {"start_time": 2.0, "end_time": 1.0},
    ],
)
def test_invalid_audio_chunk_is_rejected(kwargs):
    values = {"sequence": 0, "start_time": 0.0, "end_time": 1.0, "audio": b"a"}
    values.update(kwargs)

    with pytest.raises(AudioChunkingError):
        AudioChunk(**values)