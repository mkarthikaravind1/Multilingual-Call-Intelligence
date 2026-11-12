
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
from app.core.config import Settings


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
