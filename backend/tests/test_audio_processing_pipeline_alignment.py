from itertools import count

import pytest

from app.ai.asr.provider import ASRProvider, ASRResult, TimedText
from app.ai.language.provider import (
    LanguageIdentificationProvider,
    LanguageIdentificationResult,
    LanguageSpan,
)
from app.services.call_workflow_service import CallAnalysisResult
from app.ai.speaker.provider import (
    DiarizationProvider,
    DiarizedSegment,
    RoleIdentificationProvider,
    SpeakerRole as AIRole,
    SpeakerRoleAssignment,
)
from app.domain.utterance import SpeakerRole, Utterance
from app.services.audio_processing_pipeline import (
    AudioPipelineError,
    AudioProcessingPipeline,
)

AUDIO = b"audio"


class FakeASR(ASRProvider):
    def __init__(self, result: ASRResult) -> None:
        self._result = result

    def transcribe(self, audio: bytes) -> ASRResult:
        return self._result


class FakeLanguage(LanguageIdentificationProvider):
    def __init__(self) -> None:
        self.texts: list[str] = []

    def identify(self, text: str) -> LanguageIdentificationResult:
        self.texts.append(text)
        return LanguageIdentificationResult([LanguageSpan("en")])


class FakeDiarization(DiarizationProvider):
    def __init__(self, segments: list[DiarizedSegment]) -> None:
        self._segments = segments
        self.calls = 0

    def diarize(self, audio: bytes) -> list[DiarizedSegment]:
        self.calls += 1
        return list(self._segments)


class FakeRoles(RoleIdentificationProvider):
    def __init__(self, roles: dict[str, AIRole]) -> None:
        self._roles = roles
        self.calls = 0

    def identify_roles(
        self, segments: list[DiarizedSegment]
    ) -> list[SpeakerRoleAssignment]:
        self.calls += 1
        return [SpeakerRoleAssignment(sid, role) for sid, role in self._roles.items()]


class FakeWorkflow:
    def process_utterance(
        self, call_id: str, utterance: Utterance
    ) -> CallAnalysisResult:
        raise AssertionError("build_utterances must not call the workflow.")


def word(text: str, start: float, end: float) -> TimedText:
    return TimedText(text, start, end)


def seg(speaker_id: str, start: float, end: float) -> DiarizedSegment:
    return DiarizedSegment(speaker_id, start, end)


def asr(transcript: str, timed=(), start: float = 0.0, end: float = 3.0) -> ASRResult:
    return ASRResult(transcript, "en", start, end, timed_text=tuple(timed))


class Setup:
    def __init__(self, asr_result, segments, roles) -> None:
        ids = count()
        self.language = FakeLanguage()
        self.diarization = FakeDiarization(segments)
        self.roles = FakeRoles(roles)
        self.workflow = FakeWorkflow()
        self.pipeline = AudioProcessingPipeline(
            asr_provider=FakeASR(asr_result),
            language_provider=self.language,
            diarization_provider=self.diarization,
            role_provider=self.roles,
            workflow_service=self.workflow,
            id_factory=lambda: f"u{next(ids)}",
        )


ROLES = {"A": AIRole.ICR, "B": AIRole.CUSTOMER}


def test_one_speaker_produces_one_utterance():
    setup = Setup(
        asr("hello", [word("hello", 0.0, 1.0)], end=1.0),
        [seg("A", 0.0, 2.0)],
        ROLES,
    )

    result = setup.pipeline.build_utterances(AUDIO)

    assert len(result) == 1
    assert result[0].transcript == "hello"
    assert result[0].speaker_role is SpeakerRole.ICR
    assert result[0].languages == ("en",)
    assert (result[0].start_time, result[0].end_time) == (0.0, 1.0)


def test_alternating_speakers_produce_one_utterance_per_turn():
    timed = [word("a", 0.0, 1.0), word("b", 1.0, 2.0), word("c", 2.0, 3.0)]
    segments = [seg("A", 0.0, 1.0), seg("B", 1.0, 2.0), seg("A", 2.0, 3.0)]
    setup = Setup(asr("a b c", timed), segments, ROLES)

    result = setup.pipeline.build_utterances(AUDIO)

    assert [(u.transcript, u.speaker_role) for u in result] == [
        ("a", SpeakerRole.ICR),
        ("b", SpeakerRole.CUSTOMER),
        ("c", SpeakerRole.ICR),
    ]
    assert [u.utterance_id for u in result] == ["u0", "u1", "u2"]
    assert setup.language.texts == ["a", "b", "c"]
    assert setup.diarization.calls == 1
    assert setup.roles.calls == 1


def test_consecutive_items_of_same_speaker_share_one_utterance():
    timed = [
        word("hello", 0.0, 1.0),
        word("sir", 1.0, 2.0),
        word("how", 2.0, 3.0),
        word("are", 3.0, 4.0),
    ]
    segments = [seg("A", 0.0, 2.0), seg("B", 2.0, 4.0)]
    setup = Setup(asr("hello sir how are", timed, end=4.0), segments, ROLES)

    result = setup.pipeline.build_utterances(AUDIO)

    assert [(u.transcript, u.speaker_role) for u in result] == [
        ("hello sir", SpeakerRole.ICR),
        ("how are", SpeakerRole.CUSTOMER),
    ]
    assert [(u.start_time, u.end_time) for u in result] == [(0.0, 2.0), (2.0, 4.0)]


@pytest.mark.parametrize(
    "roles", [{"A": AIRole.ICR}, {"A": AIRole.ICR, "B": AIRole.UNKNOWN}]
)
def test_unmapped_speaker_raises(roles):
    timed = [word("a", 0.0, 1.0), word("b", 1.0, 2.0)]
    segments = [seg("A", 0.0, 1.0), seg("B", 1.0, 2.0)]
    setup = Setup(asr("a b", timed, end=2.0), segments, roles)

    with pytest.raises(AudioPipelineError, match="speaker 'B'"):
        setup.pipeline.build_utterances(AUDIO)

    assert setup.language.texts == []


def test_empty_timed_text_falls_back_to_single_utterance():
    result_asr = asr("hello sir")
    segments = [seg("A", 0.0, 1.0), seg("B", 1.0, 3.0)]

    result = Setup(result_asr, segments, ROLES).pipeline.build_utterances(AUDIO)
    expected = Setup(result_asr, segments, ROLES).pipeline.build_utterance(AUDIO)

    assert result == [expected]
    assert result[0].speaker_role is SpeakerRole.CUSTOMER


def test_start_offset_applies_to_every_utterance():
    timed = [word("a", 0.5, 1.0), word("b", 1.0, 2.0)]
    segments = [seg("A", 0.0, 1.0), seg("B", 1.0, 2.0)]
    setup = Setup(asr("a b", timed, end=2.0), segments, ROLES)

    result = setup.pipeline.build_utterances(AUDIO, start_offset=10.0)

    assert [(u.start_time, u.end_time) for u in result] == [(10.5, 11.0), (11.0, 12.0)]


def test_build_utterance_still_returns_single_utterance_for_timed_text():
    timed = [word("hello", 0.0, 1.0), word("there", 1.0, 3.0)]
    segments = [seg("A", 0.0, 1.0), seg("B", 1.0, 3.0)]
    setup = Setup(asr("hello there", timed), segments, ROLES)

    result = setup.pipeline.build_utterance(AUDIO, start_offset=5.0)

    assert isinstance(result, Utterance)
    assert result.transcript == "hello there"
    assert result.speaker_role is SpeakerRole.CUSTOMER
    assert (result.start_time, result.end_time) == (5.0, 8.0)
    assert setup.language.texts == ["hello there"]


def test_no_speaker_overlap_raises():
    setup = Setup(
        asr("x", [word("x", 5.0, 6.0)], end=6.0), [seg("A", 0.0, 1.0)], ROLES
    )

    with pytest.raises(AudioPipelineError, match="overlaps"):
        setup.pipeline.build_utterances(AUDIO)


def test_invalid_timed_text_raises():
    result_asr = ASRResult("x", "en", 0.0, 1.0, timed_text=("x",))  # type: ignore[arg-type]
    setup = Setup(result_asr, [seg("A", 0.0, 1.0)], ROLES)

    with pytest.raises(AudioPipelineError, match="timed text"):
        setup.pipeline.build_utterances(AUDIO)


def test_build_utterances_validates_input():
    setup = Setup(asr("x"), [seg("A", 0.0, 1.0)], ROLES)

    with pytest.raises(AudioPipelineError, match="audio"):
        setup.pipeline.build_utterances(b"")
    with pytest.raises(AudioPipelineError, match="start_offset"):
        setup.pipeline.build_utterances(AUDIO, start_offset=-1.0)