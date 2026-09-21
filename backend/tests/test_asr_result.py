import dataclasses

import pytest

from app.ai.asr.provider import ASRResult, TimedText


def test_timed_text_defaults_to_empty():
    assert ASRResult("hi", "en", 0.0, 1.0).timed_text == ()


def test_positional_construction_is_unchanged():
    result = ASRResult("hi", "en", 1.0, 3.0, 0.9)
    assert result.confidence == 0.9
    assert result.timed_text == ()

def test_timed_text_is_immutable():
    item = TimedText("a", 0.0, 1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(item, "text", "b")