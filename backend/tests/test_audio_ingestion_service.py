import wave
from pathlib import Path

import pytest

from app.services.audio_ingestion_service import (
    AudioIngestionError,
    AudioIngestionService,
    AudioMetadata,
    IngestedAudio,
)


def write_wav(
    path: Path,
    frames: int = 16000,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
) -> Path:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00" * frames * channels * sample_width)
    return path


@pytest.fixture
def service() -> AudioIngestionService:
    return AudioIngestionService()


def test_load_wav_returns_file_bytes_and_metadata(tmp_path, service):
    path = write_wav(tmp_path / "call.wav", frames=8000)

    result = service.load_wav(path)

    assert isinstance(result, IngestedAudio)
    assert result.audio == path.read_bytes()
    assert result.metadata == AudioMetadata(
        sample_rate=16000,
        channels=1,
        sample_width_bytes=2,
        frame_count=8000,
        duration_seconds=0.5,
        size_bytes=path.stat().st_size,
    )


def test_load_wav_accepts_string_path(tmp_path, service):
    path = write_wav(tmp_path / "call.wav")

    result = service.load_wav(str(path))

    assert result.audio == path.read_bytes()


def test_load_wav_reports_stereo_metadata(tmp_path, service):
    path = write_wav(
        tmp_path / "stereo.wav", frames=44100, sample_rate=44100, channels=2
    )

    metadata = service.load_wav(path).metadata

    assert metadata.channels == 2
    assert metadata.sample_rate == 44100
    assert metadata.duration_seconds == pytest.approx(1.0)


def test_load_wav_raises_for_missing_file(tmp_path, service):
    with pytest.raises(AudioIngestionError, match="not found"):
        service.load_wav(tmp_path / "missing.wav")


def test_load_wav_raises_for_directory(tmp_path, service):
    with pytest.raises(AudioIngestionError, match="not found"):
        service.load_wav(tmp_path)


def test_load_wav_raises_for_empty_file(tmp_path, service):
    path = tmp_path / "empty.wav"
    path.write_bytes(b"")

    with pytest.raises(AudioIngestionError, match="empty"):
        service.load_wav(path)


def test_load_wav_raises_for_non_wav_content(tmp_path, service):
    path = tmp_path / "fake.wav"
    path.write_bytes(b"this is not a wav file")

    with pytest.raises(AudioIngestionError, match="valid WAV"):
        service.load_wav(path)


def test_load_wav_raises_for_wav_without_frames(tmp_path, service):
    path = write_wav(tmp_path / "silent.wav", frames=0)

    with pytest.raises(AudioIngestionError, match="no audio frames"):
        service.load_wav(path)


def test_ingested_audio_is_non_empty_bytes_for_pipeline(tmp_path, service):
    result = service.load_wav(write_wav(tmp_path / "call.wav"))

    assert isinstance(result.audio, bytes)
    assert result.audio