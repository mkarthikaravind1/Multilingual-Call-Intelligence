import pytest

from app.ai.speaker.provider import DiarizedSegment
from app.ai.speaker.scripted_diarization_provider import ScriptedDiarizationProvider
from app.composition import providers
from app.composition.providers import (
    UnsupportedProviderError,
    create_diarization_provider,
)
from app.core.config import Settings


class Recorder:
    captured: dict = {}

    def __init__(self, **kwargs) -> None:
        Recorder.captured = kwargs


def test_scripted_still_supported() -> None:
    segments = [DiarizedSegment("S1", 0.0, 1.0)]
    provider = create_diarization_provider(
        segments, Settings(diarization_provider="scripted")
    )
    assert isinstance(provider, ScriptedDiarizationProvider)
    assert provider.diarize(b"audio") == segments


def test_pyannote_builds_provider_with_model_and_token(monkeypatch) -> None:
    monkeypatch.setattr(providers, "PyannoteDiarizationProvider", Recorder)
    settings = Settings(
        diarization_provider=" Pyannote ",
        pyannote_model="custom/model",
        huggingface_token="tok",
    )
    provider = create_diarization_provider((), settings)
    assert isinstance(provider, Recorder)
    assert Recorder.captured == {"model": "custom/model", "token": "tok"}


def test_pyannote_empty_token_becomes_none(monkeypatch) -> None:
    monkeypatch.setattr(providers, "PyannoteDiarizationProvider", Recorder)
    settings = Settings(
        diarization_provider="pyannote",
        pyannote_model="custom/model",
        huggingface_token="",
    )
    create_diarization_provider((), settings)
    assert Recorder.captured["token"] is None


def test_unknown_provider_lists_pyannote_as_available() -> None:
    with pytest.raises(UnsupportedProviderError, match="pyannote"):
        create_diarization_provider((), Settings(diarization_provider="nope"))