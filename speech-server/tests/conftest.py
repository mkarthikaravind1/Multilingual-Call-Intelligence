import io
import os
import sys
from pathlib import Path

# Ensure project root is first on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import wave
import numpy as np
import pytest
from starlette.testclient import TestClient

from app.config import get_settings
from app.engine import set_engine
from app.engine.fake import FakeSTTEngine
from app.main import app


@pytest.fixture(autouse=True)
def setup_fake_engine():
    """Ensures FakeSTTEngine is active for all tests without downloading models."""
    fake = FakeSTTEngine(model_name="mock-indic-whisper", device="cpu", loaded=True)
    set_engine(fake)
    # Reset token by default
    settings = get_settings()
    settings.SPEECH_SERVER_TOKEN = None
    yield fake
    set_engine(None)


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)


def make_wav_bytes(
    duration_seconds: float = 1.0,
    sample_rate: int = 16000,
    frequency: float = 440.0,
    amplitude: float = 0.5,
    channels: int = 1,
) -> bytes:
    """Helper to generate in-memory valid PCM WAV audio bytes."""
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    if amplitude > 0.0:
        samples = (amplitude * np.sin(2 * np.pi * frequency * t) * 32767.0).astype(np.int16)
    else:
        samples = np.zeros(len(t), dtype=np.int16)

    if channels == 2:
        samples = np.column_stack((samples, samples)).flatten()

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


def make_raw_pcm_bytes(
    duration_seconds: float = 1.0,
    sample_rate: int = 16000,
    frequency: float = 440.0,
    amplitude: float = 0.5,
) -> bytes:
    """Helper to generate raw 16-bit little-endian PCM bytes."""
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    if amplitude > 0.0:
        samples = (amplitude * np.sin(2 * np.pi * frequency * t) * 32767.0).astype("<i2")
    else:
        samples = np.zeros(len(t), dtype="<i2")
    return samples.tobytes()
