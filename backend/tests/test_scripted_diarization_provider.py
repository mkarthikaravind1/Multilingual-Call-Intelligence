import pytest

from app.ai.speaker.provider import DiarizationProvider, DiarizedSegment
from app.ai.speaker.scripted_diarization_provider import ScriptedDiarizationProvider


def make_segments() -> list[DiarizedSegment]:
    return [
        DiarizedSegment(speaker_id="S2", start_time=2.0, end_time=4.0, confidence=0.9),
        DiarizedSegment(speaker_id="S1", start_time=0.0, end_time=2.0),
    ]


def test_is_diarization_provider() -> None:
    assert isinstance(ScriptedDiarizationProvider([]), DiarizationProvider)


def test_returns_segments_ordered_by_start_time() -> None:
    result = ScriptedDiarizationProvider(make_segments()).diarize(b"audio")
    assert [s.speaker_id for s in result] == ["S1", "S2"]


def test_preserves_times_and_confidence() -> None:
    result = ScriptedDiarizationProvider(make_segments()).diarize(b"audio")
    assert (result[1].start_time, result[1].end_time, result[1].confidence) == (
        2.0,
        4.0,
        0.9,
    )
    assert result[0].confidence is None


def test_output_does_not_depend_on_audio_content() -> None:
    provider = ScriptedDiarizationProvider(make_segments())
    assert provider.diarize(b"a") == provider.diarize(b"completely different")


def test_empty_script_returns_empty_list() -> None:
    assert ScriptedDiarizationProvider([]).diarize(b"audio") == []


def test_mutating_result_does_not_affect_later_calls() -> None:
    provider = ScriptedDiarizationProvider(make_segments())
    first = provider.diarize(b"audio")
    first[0].speaker_id = "CHANGED"
    first.pop()
    second = provider.diarize(b"audio")
    assert [s.speaker_id for s in second] == ["S1", "S2"]


def test_mutating_source_segments_does_not_affect_provider() -> None:
    source = make_segments()
    provider = ScriptedDiarizationProvider(source)
    source[0].speaker_id = "CHANGED"
    source.clear()
    assert [s.speaker_id for s in provider.diarize(b"audio")] == ["S1", "S2"]


def test_rejects_empty_speaker_id() -> None:
    with pytest.raises(ValueError, match="speaker_id"):
        ScriptedDiarizationProvider([DiarizedSegment("  ", 0.0, 1.0)])


def test_rejects_end_before_start() -> None:
    with pytest.raises(ValueError, match="end_time"):
        ScriptedDiarizationProvider([DiarizedSegment("S1", 2.0, 1.0)])