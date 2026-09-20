import pytest

from app.ai.asr.provider import ASRProvider, ASRResult
from app.ai.language.provider import (
    LanguageIdentificationProvider,
    LanguageIdentificationResult,
    LanguageSpan,
)
from app.ai.speaker.provider import (
    DiarizationProvider,
    DiarizedSegment,
    SpeakerRole as AISpeakerRole,
)
from app.ai.speaker.scripted_diarization_provider import ScriptedDiarizationProvider
from app.ai.speaker.static_role_provider import StaticRoleIdentificationProvider
from app.domain.utterance import SpeakerRole
from app.services.audio_processing_pipeline import (
    AudioPipelineError,
    AudioProcessingPipeline,
)
from typing import cast
from app.domain.utterance import SpeakerRole, Utterance
from app.services.call_workflow_service import CallAnalysisResult

ROLES = {
    "S1": AISpeakerRole.ICR,
    "S2": AISpeakerRole.CUSTOMER,
    "S3": AISpeakerRole.UNKNOWN,
}


class FakeASR(ASRProvider):
    def transcribe(self, audio: bytes) -> ASRResult:
        return ASRResult(
            transcript="hello",
            detected_language="en",
            start_time=0.0,
            end_time=2.0,
            confidence=0.9,
        )


class FakeLanguage(LanguageIdentificationProvider):
    def identify(self, text: str) -> LanguageIdentificationResult:
        return LanguageIdentificationResult(languages=[LanguageSpan(language="en")])


class SequencedDiarization(DiarizationProvider):
    def __init__(self, *scripts: list[DiarizedSegment]) -> None:
        self._providers = [ScriptedDiarizationProvider(script) for script in scripts]
        self._index = 0

    def diarize(self, audio: bytes) -> list[DiarizedSegment]:
        provider = self._providers[self._index]
        self._index += 1
        return provider.diarize(audio)


ANALYSIS = cast(CallAnalysisResult, object())


class RecordingWorkflow:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Utterance]] = []

    def process_utterance(
        self, call_id: str, utterance: Utterance
    ) -> CallAnalysisResult:
        self.calls.append((call_id, utterance))
        return ANALYSIS


def make_pipeline(
    diarization: DiarizationProvider, workflow: RecordingWorkflow | None = None
) -> AudioProcessingPipeline:
    return AudioProcessingPipeline(
        asr_provider=FakeASR(),
        language_provider=FakeLanguage(),
        diarization_provider=diarization,
        role_provider=StaticRoleIdentificationProvider(ROLES),
        workflow_service=workflow if workflow is not None else RecordingWorkflow(),
        id_factory=lambda: "utt-1",
    )


def single_speaker(speaker_id: str) -> ScriptedDiarizationProvider:
    return ScriptedDiarizationProvider([DiarizedSegment(speaker_id, 0.0, 2.0)])


@pytest.mark.parametrize(
    ("speaker_id", "expected"),
    [("S1", SpeakerRole.ICR), ("S2", SpeakerRole.CUSTOMER)],
)
def test_ai_roles_map_to_domain_roles(speaker_id: str, expected: SpeakerRole) -> None:
    utterance = make_pipeline(single_speaker(speaker_id)).build_utterance(b"audio")
    assert utterance.speaker_role is expected


def test_unknown_role_raises_pipeline_error() -> None:
    with pytest.raises(AudioPipelineError, match="No usable role"):
        make_pipeline(single_speaker("S3")).build_utterance(b"audio")


def test_speaker_missing_from_role_mapping_raises_pipeline_error() -> None:
    with pytest.raises(AudioPipelineError, match="No usable role"):
        make_pipeline(single_speaker("S9")).build_utterance(b"audio")


def test_unknown_role_never_reaches_workflow() -> None:
    workflow = RecordingWorkflow()
    with pytest.raises(AudioPipelineError):
        make_pipeline(single_speaker("S3"), workflow).process_audio("call-1", b"audio")
    assert workflow.calls == []


def test_call_id_and_domain_utterance_reach_workflow() -> None:
    workflow = RecordingWorkflow()
    result = make_pipeline(single_speaker("S1"), workflow).process_audio(
        "call-1", b"audio", start_offset=5.0
    )
    call_id, utterance = workflow.calls[0]
    assert call_id == "call-1"
    assert utterance.speaker_role is SpeakerRole.ICR
    assert (utterance.start_time, utterance.end_time) == (5.0, 7.0)
    assert result is ANALYSIS


def test_speaker_role_is_stable_across_chunks() -> None:
    diarization = SequencedDiarization(
        [DiarizedSegment("S2", 0.0, 2.0)],
        [DiarizedSegment("S1", 0.0, 0.5), DiarizedSegment("S2", 0.5, 2.0)],
    )
    pipeline = make_pipeline(diarization)
    first = pipeline.build_utterance(b"chunk-1")
    second = pipeline.build_utterance(b"chunk-2")
    assert first.speaker_role is SpeakerRole.CUSTOMER
    assert second.speaker_role is SpeakerRole.CUSTOMER