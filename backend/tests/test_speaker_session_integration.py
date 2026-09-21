import pytest

from app.ai.asr.provider import ASRProvider, ASRResult
from app.ai.language.provider import (
    LanguageIdentificationProvider,
    LanguageIdentificationResult,
    LanguageSpan,
)
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.speaker.provider import DiarizedSegment
from app.composition.services import (
    build_audio_processing_pipeline,
    build_call_service,
    build_call_workflow_service,
)
from app.composition.speaker_sessions import (
    build_session_role_provider,
    build_speaker_session_registry,
)
from app.core.config import Settings
from app.domain.utterance import SpeakerRole
from app.services.audio_processing_pipeline import AudioPipelineError


class FakeLLMClient(LLMClient):
    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(text="[]")


class FakeASRProvider(ASRProvider):
    def transcribe(self, audio: bytes) -> ASRResult:
        return ASRResult(
            transcript="The bill is too high",
            detected_language="en",
            start_time=0.0,
            end_time=2.0,
        )


class FakeLanguageProvider(LanguageIdentificationProvider):
    def identify(self, text: str) -> LanguageIdentificationResult:
        return LanguageIdentificationResult(languages=[LanguageSpan(language="en")])


def make_settings() -> Settings:
    return Settings(
        _env_file=None, # type: ignore
        diarization_provider="scripted",
        role_provider="order_based",
    )  # type: ignore


def make_calls(*call_ids: str):
    call_service = build_call_service()
    workflow = build_call_workflow_service(
        llm_client=FakeLLMClient(), call_service=call_service
    )
    for call_id in call_ids:
        call_service.start_call(call_id)
    return call_service, workflow


def process_chunk(workflow, call_id, role_provider, speaker_id, offset):
    pipeline = build_audio_processing_pipeline(
        workflow,
        [DiarizedSegment(speaker_id, 0.0, 2.0)],
        settings=make_settings(),
        asr_provider=FakeASRProvider(),
        language_provider=FakeLanguageProvider(),
        role_provider=role_provider,
    )
    pipeline.process_audio(call_id, b"audio", start_offset=offset)


def roles_of(call_service, call_id):
    return [u.speaker_role for u in call_service.get_call(call_id).utterances]


def test_roles_stay_stable_across_chunks_through_unchanged_pipeline():
    call_service, workflow = make_calls("call-1")
    registry = build_speaker_session_registry()
    role_provider = build_session_role_provider(registry.get_or_create("call-1"))

    for index, speaker in enumerate(["s0", "s1", "s0", "s1"]):
        process_chunk(workflow, "call-1", role_provider, speaker, index * 2.0)

    assert roles_of(call_service, "call-1") == [
        SpeakerRole.ICR,
        SpeakerRole.CUSTOMER,
        SpeakerRole.ICR,
        SpeakerRole.CUSTOMER,
    ]


def test_unknown_speaker_surfaces_existing_pipeline_error():
    call_service, workflow = make_calls("call-1")
    registry = build_speaker_session_registry()
    role_provider = build_session_role_provider(registry.get_or_create("call-1"))
    process_chunk(workflow, "call-1", role_provider, "s0", 0.0)
    process_chunk(workflow, "call-1", role_provider, "s1", 2.0)

    with pytest.raises(AudioPipelineError, match="No usable role"):
        process_chunk(workflow, "call-1", role_provider, "s2", 4.0)

    assert call_service.get_call("call-1").utterance_count == 2


def test_separate_calls_keep_independent_speaker_mappings():
    call_service, workflow = make_calls("call-1", "call-2")
    registry = build_speaker_session_registry()
    provider_one = build_session_role_provider(registry.get_or_create("call-1"))
    provider_two = build_session_role_provider(registry.get_or_create("call-2"))

    process_chunk(workflow, "call-1", provider_one, "s0", 0.0)
    process_chunk(workflow, "call-1", provider_one, "s1", 2.0)
    process_chunk(workflow, "call-2", provider_two, "s1", 0.0)

    assert roles_of(call_service, "call-1") == [SpeakerRole.ICR, SpeakerRole.CUSTOMER]
    assert roles_of(call_service, "call-2") == [SpeakerRole.ICR]