from dataclasses import dataclass

import pytest
from typing import Any
from app.ai.asr.provider import ASRProvider, ASRResult
from app.ai.language.provider import (
    LanguageIdentificationProvider,
    LanguageIdentificationResult,
    LanguageSpan,
)
from app.ai.speaker.provider import (
    DiarizationProvider,
    DiarizedSegment,
    RoleIdentificationProvider,
    SpeakerRole as AISpeakerRole,
    SpeakerRoleAssignment,
)
from app.domain.utterance import SpeakerRole, Utterance
from app.services.audio_processing_pipeline import (
    AudioPipelineError,
    AudioProcessingPipeline,
)

AUDIO = b"fake-audio-bytes"
RESULT:Any = object()


def _respond(value):
    if isinstance(value, Exception):
        raise value
    return value


class FakeASR(ASRProvider):
    def __init__(self, value):
        self.value = value
        self.calls: list[bytes] = []

    def transcribe(self, audio):
        self.calls.append(audio)
        return _respond(self.value)


class FakeLanguage(LanguageIdentificationProvider):
    def __init__(self, value):
        self.value = value
        self.calls: list[str] = []

    def identify(self, text):
        self.calls.append(text)
        return _respond(self.value)


class FakeDiarizer(DiarizationProvider):
    def __init__(self, value):
        self.value = value
        self.calls: list[bytes] = []

    def diarize(self, audio):
        self.calls.append(audio)
        return _respond(self.value)


class FakeRoles(RoleIdentificationProvider):
    def __init__(self, value):
        self.value = value
        self.calls: list[list[DiarizedSegment]] = []

    def identify_roles(self, segments):
        self.calls.append(segments)
        return _respond(self.value)


class FakeWorkflow:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[tuple[str, Utterance]] = []

    def process_utterance(self, call_id, utterance):
        self.calls.append((call_id, utterance))
        if self.error:
            raise self.error
        return RESULT


@dataclass
class Setup:
    asr: FakeASR
    language: FakeLanguage
    diarizer: FakeDiarizer
    roles: FakeRoles
    workflow: FakeWorkflow
    pipeline: AudioProcessingPipeline


def make_setup(**overrides) -> Setup:
    values = {
        "asr": ASRResult("vanakkam sir", "ta", 1.0, 3.0, 0.9),
        "language": LanguageIdentificationResult([LanguageSpan("ta", 0.95)]),
        "segments": [DiarizedSegment("spk_0", 0.0, 4.0, 0.9)],
        "assignments": [SpeakerRoleAssignment("spk_0", AISpeakerRole.CUSTOMER, 0.9)],
        "workflow_error": None,
        
    }
    values.update(overrides)

    asr = FakeASR(values["asr"])
    language = FakeLanguage(values["language"])
    diarizer = FakeDiarizer(values["segments"])
    roles = FakeRoles(values["assignments"])
    workflow = FakeWorkflow(values["workflow_error"])
    pipeline = AudioProcessingPipeline(asr, language, diarizer, roles, workflow, id_factory=lambda: "utt-1")
    
    return Setup(asr, language, diarizer, roles, workflow, pipeline)


def test_successful_processing_builds_utterance_and_calls_workflow():
    setup = make_setup()

    result = setup.pipeline.process_audio("call-1", AUDIO)

    assert result is RESULT
    assert len(setup.workflow.calls) == 1
    call_id, utterance = setup.workflow.calls[0]
    assert call_id == "call-1"
    assert isinstance(utterance, Utterance)
    assert utterance.transcript == "vanakkam sir"
    assert utterance.speaker_role is SpeakerRole.CUSTOMER
    assert utterance.languages == ("ta",)
    assert (utterance.start_time, utterance.end_time) == (1.0, 3.0)
    assert utterance.confidence == 0.9
    assert utterance.utterance_id == "utt-1"


def test_call_id_is_passed_through_unchanged():
    setup = make_setup()

    setup.pipeline.process_audio("call-xyz-42", AUDIO)

    assert setup.workflow.calls[0][0] == "call-xyz-42"


def test_providers_receive_expected_inputs():
    setup = make_setup()

    setup.pipeline.process_audio("call-1", AUDIO)

    assert setup.asr.calls == [AUDIO]
    assert setup.language.calls == ["vanakkam sir"]
    assert setup.diarizer.calls == [AUDIO]
    assert setup.roles.calls == [setup.diarizer.value]


def test_build_utterance_does_not_touch_workflow():
    setup = make_setup()

    utterance = setup.pipeline.build_utterance(AUDIO)

    assert isinstance(utterance, Utterance)
    assert setup.workflow.calls == []


@pytest.mark.parametrize(
    ("ai_role", "domain_role"),
    [
        (AISpeakerRole.ICR, SpeakerRole.ICR),
        (AISpeakerRole.CUSTOMER, SpeakerRole.CUSTOMER),
    ],
)
def test_speaker_role_is_mapped_to_domain_role(ai_role, domain_role):
    setup = make_setup(assignments=[SpeakerRoleAssignment("spk_0", ai_role)])

    utterance = setup.pipeline.build_utterance(AUDIO)

    assert utterance.speaker_role is domain_role


def test_speaker_with_largest_overlap_is_selected():
    setup = make_setup(
        segments=[
            DiarizedSegment("spk_0", 0.0, 1.5),
            DiarizedSegment("spk_1", 1.5, 4.0),
        ],
        assignments=[
            SpeakerRoleAssignment("spk_0", AISpeakerRole.ICR),
            SpeakerRoleAssignment("spk_1", AISpeakerRole.CUSTOMER),
        ],
    )

    assert setup.pipeline.build_utterance(AUDIO).speaker_role is SpeakerRole.CUSTOMER


def test_overlap_is_summed_across_segments_of_same_speaker():
    setup = make_setup(
        segments=[
            DiarizedSegment("spk_0", 0.0, 1.2),
            DiarizedSegment("spk_1", 1.2, 2.0),
            DiarizedSegment("spk_0", 2.0, 4.0),
        ],
        assignments=[
            SpeakerRoleAssignment("spk_0", AISpeakerRole.ICR),
            SpeakerRoleAssignment("spk_1", AISpeakerRole.CUSTOMER),
        ],
    )

    assert setup.pipeline.build_utterance(AUDIO).speaker_role is SpeakerRole.ICR


def test_start_offset_shifts_utterance_times_only():
    setup = make_setup()

    utterance = setup.pipeline.build_utterance(AUDIO, start_offset=10.0)

    assert (utterance.start_time, utterance.end_time) == (11.0, 13.0)
    assert utterance.speaker_role is SpeakerRole.CUSTOMER


def test_negative_start_offset_is_rejected():
    setup = make_setup()

    with pytest.raises(AudioPipelineError):
        setup.pipeline.build_utterance(AUDIO, start_offset=-1.0)

    assert setup.asr.calls == []


def test_mixed_language_result_is_preserved_in_order():
    setup = make_setup(
        language=LanguageIdentificationResult(
            [LanguageSpan("en"), LanguageSpan("ta")]
        )
    )

    utterance = setup.pipeline.build_utterance(AUDIO)

    assert utterance.languages == ("en", "ta")
    assert utterance.is_mixed_language is True


def test_duplicate_language_spans_are_collapsed():
    setup = make_setup(
        language=LanguageIdentificationResult(
            [LanguageSpan("ta"), LanguageSpan("ta"), LanguageSpan("en")]
        )
    )

    assert setup.pipeline.build_utterance(AUDIO).languages == ("ta", "en")


def test_language_provider_is_independent_of_asr_detected_language():
    setup = make_setup(
        asr=ASRResult("vanakkam sir", "en", 1.0, 3.0),
        language=LanguageIdentificationResult([LanguageSpan("ta")]),
    )

    assert setup.pipeline.build_utterance(AUDIO).languages == ("ta",)


def test_falls_back_to_asr_language_when_language_provider_finds_none():
    setup = make_setup(
        asr=ASRResult("hello", "en", 1.0, 3.0),
        language=LanguageIdentificationResult([]),
    )

    assert setup.pipeline.build_utterance(AUDIO).languages == ("en",)


INVALID_RESULT_CASES = {
    "asr_wrong_type": {"asr": "not-a-result"},
    "asr_none": {"asr": None},
    "asr_empty_transcript": {"asr": ASRResult("   ", "ta", 1.0, 3.0)},
    "asr_inverted_times": {"asr": ASRResult("hi", "en", 3.0, 1.0)},
    "asr_confidence_out_of_range": {"asr": ASRResult("hi", "en", 1.0, 3.0, 1.5)},
    "language_wrong_type": {"language": ["ta"]},
    "language_span_wrong_type": {"language": LanguageIdentificationResult(["ta"])}, # type: ignore
    "language_unsupported_code": {
        "language": LanguageIdentificationResult([LanguageSpan("fr")])
    },
    "asr_fallback_unsupported_code": {
        "asr": ASRResult("hi", "xx", 1.0, 3.0),
        "language": LanguageIdentificationResult([]),
    },
    "no_diarized_segments": {"segments": []},
    "segments_wrong_type": {"segments": "segments"},
    "segment_element_wrong_type": {"segments": ["segment"]},
    "assignments_wrong_type": {"assignments": None},
    "assignment_element_wrong_type": {"assignments": ["assignment"]},
    "speaker_without_assignment": {
        "assignments": [SpeakerRoleAssignment("other", AISpeakerRole.ICR)]
    },
    "unknown_role": {
        "assignments": [SpeakerRoleAssignment("spk_0", AISpeakerRole.UNKNOWN)]
    },
    "no_overlap_with_speech": {"segments": [DiarizedSegment("spk_0", 10.0, 12.0)]},
}


@pytest.mark.parametrize(
    "overrides", INVALID_RESULT_CASES.values(), ids=INVALID_RESULT_CASES.keys()
)
def test_invalid_provider_results_raise_pipeline_error(overrides):
    setup = make_setup(**overrides)

    with pytest.raises(AudioPipelineError):
        setup.pipeline.process_audio("call-1", AUDIO)

    assert setup.workflow.calls == []


def test_empty_audio_is_rejected_before_any_provider_call():
    setup = make_setup()

    with pytest.raises(AudioPipelineError):
        setup.pipeline.process_audio("call-1", b"")

    assert setup.asr.calls == []
    assert setup.language.calls == []
    assert setup.diarizer.calls == []
    assert setup.workflow.calls == []


def test_empty_transcript_stops_before_language_and_speaker_providers():
    setup = make_setup(asr=ASRResult("  ", "ta", 1.0, 3.0))

    with pytest.raises(AudioPipelineError):
        setup.pipeline.process_audio("call-1", AUDIO)

    assert setup.language.calls == []
    assert setup.diarizer.calls == []


PROVIDER_FAILURE_CASES = {
    "asr": {"asr": RuntimeError("asr down")},
    "language": {"language": RuntimeError("language down")},
    "diarizer": {"segments": RuntimeError("diarizer down")},
    "roles": {"assignments": RuntimeError("roles down")},
}


@pytest.mark.parametrize(
    "overrides", PROVIDER_FAILURE_CASES.values(), ids=PROVIDER_FAILURE_CASES.keys()
)
def test_provider_exceptions_propagate_without_reaching_workflow(overrides):
    setup = make_setup(**overrides)

    with pytest.raises(RuntimeError):
        setup.pipeline.process_audio("call-1", AUDIO)

    assert setup.workflow.calls == []


def test_asr_failure_prevents_downstream_provider_calls():
    setup = make_setup(asr=RuntimeError("asr down"))

    with pytest.raises(RuntimeError):
        setup.pipeline.process_audio("call-1", AUDIO)

    assert setup.language.calls == []
    assert setup.diarizer.calls == []
    assert setup.roles.calls == []


def test_workflow_exception_propagates():
    setup = make_setup(workflow_error=RuntimeError("workflow failed"))

    with pytest.raises(RuntimeError, match="workflow failed"):
        setup.pipeline.process_audio("call-1", AUDIO)

def test_default_id_factory_generates_unique_ids():
    setup = make_setup()
    pipeline = AudioProcessingPipeline(
        setup.asr, setup.language, setup.diarizer, setup.roles, setup.workflow
    )

    first = pipeline.build_utterance(AUDIO)
    second = pipeline.build_utterance(AUDIO)

    assert first.utterance_id != second.utterance_id

def test_empty_generated_id_raises_pipeline_error():
    setup = make_setup()
    pipeline = AudioProcessingPipeline(
        setup.asr, setup.language, setup.diarizer, setup.roles, setup   .workflow,
        id_factory=lambda: "  ",
    )

    with pytest.raises(AudioPipelineError):
        pipeline.process_audio("call-1", AUDIO)

    assert setup.workflow.calls == []