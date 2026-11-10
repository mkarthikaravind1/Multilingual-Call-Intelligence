from starlette.testclient import TestClient
from tests.conftest import make_wav_bytes


def test_transcribe_valid_audio(client: TestClient):
    """POST /v1/transcribe returns 200 and matches required JSON schema."""
    audio_data = make_wav_bytes(duration_seconds=2.0, sample_rate=16000, frequency=300.0)
    response = client.post(
        "/v1/transcribe",
        files={"file": ("test.wav", audio_data, "audio/wav")},
    )
    assert response.status_code == 200
    data = response.json()

    assert "transcript" in data
    assert "language" in data
    assert "confidence" in data
    assert "duration" in data
    assert "no_speech" in data
    assert "segments" in data

    assert data["language"] in ("ta", "en", "te", "kn", "ml")
    assert data["no_speech"] is False
    assert len(data["segments"]) > 0
    assert data["duration"] == 2.0


def test_transcribe_language_hint(client: TestClient):
    """POST /v1/transcribe with specific language code."""
    audio_data = make_wav_bytes(duration_seconds=1.5, sample_rate=16000)

    for lang in ["ta", "en", "te", "kn", "ml"]:
        response = client.post(
            "/v1/transcribe",
            data={"language": lang},
            files={"file": ("test.wav", audio_data, "audio/wav")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["language"] == lang


def test_transcribe_resample_from_8khz(client: TestClient):
    """Audio recorded at 8 kHz is successfully decoded and resampled."""
    audio_8k = make_wav_bytes(duration_seconds=1.0, sample_rate=8000)
    response = client.post(
        "/v1/transcribe",
        files={"file": ("tel_8k.wav", audio_8k, "audio/wav")},
    )
    assert response.status_code == 200
    data = response.json()
    assert abs(data["duration"] - 1.0) < 0.05


def test_transcribe_silence(client: TestClient):
    """Silent audio returns 200 with no_speech=True, empty transcript, and empty segments."""
    silence = make_wav_bytes(duration_seconds=1.5, amplitude=0.0)
    response = client.post(
        "/v1/transcribe",
        files={"file": ("silence.wav", silence, "audio/wav")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["no_speech"] is True
    assert data["transcript"] == ""
    assert data["segments"] == []


def test_transcribe_longer_than_30s_returns_413(client: TestClient):
    """Audio exceeding 30s is rejected with 413."""
    long_audio = make_wav_bytes(duration_seconds=31.0)
    response = client.post(
        "/v1/transcribe",
        files={"file": ("too_long.wav", long_audio, "audio/wav")},
    )
    assert response.status_code == 413
    assert "exceeds maximum allowed duration" in response.json()["detail"]


def test_transcribe_corrupted_audio_returns_400(client: TestClient):
    """Undecodable or corrupted audio bytes return 400."""
    corrupt_bytes = b"NOT_A_VALID_AUDIO_FILE_DATA_12345"
    response = client.post(
        "/v1/transcribe",
        files={"file": ("bad.wav", corrupt_bytes, "audio/wav")},
    )
    assert response.status_code == 400
    assert "Cannot decode audio file" in response.json()["detail"]

