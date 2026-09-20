import pytest

from app.ai.asr.provider import ASRProvider, ASRResult
from app.ai.language.provider import (
    LanguageIdentificationProvider,
    LanguageIdentificationResult,
    LanguageSpan,
)
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.sentiment.provider import SentimentResult
from app.ai.speaker.provider import DiarizedSegment
from app.composition import providers
from app.composition.providers import UnsupportedProviderError
from app.composition.services import (
    build_audio_processing_pipeline,
    build_call_service,
    build_call_workflow_service,
    build_conversation_repository,
    build_coverage_repository,
)
from app.core.config import Settings
from app.domain.utterance import SpeakerRole, Utterance
from app.services.audio_processing_pipeline import AudioProcessingPipeline
from app.services.call_workflow_service import CallAnalysisResult


class FakeLLMClient(LLMClient):
    def __init__(self, model: str | None = None) -> None:
        self.model = model
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
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


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides) # type: ignore


def make_utterance() -> Utterance:
    return Utterance(
        utterance_id="u-1",
        transcript="The bill is too high",
        speaker_role=SpeakerRole.CUSTOMER,
        languages=("en",),
        start_time=0.0,
        end_time=2.0,
    )


def test_repository_builders_return_fresh_empty_repositories():
    assert build_conversation_repository() is not build_conversation_repository()
    assert build_conversation_repository().get("call-1") is None
    assert build_coverage_repository().get("call-1") is None


def test_call_workflow_service_processes_utterance_with_injected_llm_client():
    call_service = build_call_service()
    workflow = build_call_workflow_service(
        llm_client=FakeLLMClient(), call_service=call_service
    )
    call_service.start_call("call-1")

    result = workflow.process_utterance("call-1", make_utterance())

    assert isinstance(result, CallAnalysisResult)
    assert result.coverage.call_id == "call-1"
    assert isinstance(result.sentiment, SentimentResult)
    assert result.question_suggestion is None
    assert call_service.get_call("call-1").utterance_count == 1


def test_call_workflow_service_selects_llm_client_from_settings(monkeypatch):
    created: list[FakeLLMClient] = []

    def fake_groq(model: str | None = None) -> FakeLLMClient:
        client = FakeLLMClient(model)
        created.append(client)
        return client

    monkeypatch.setattr(providers, "GroqLLMClient", fake_groq)
    call_service = build_call_service()
    workflow = build_call_workflow_service(
        settings=make_settings(llm_provider="groq", groq_model="test-model"),
        call_service=call_service,
    )
    call_service.start_call("call-1")

    workflow.process_utterance("call-1", make_utterance())

    assert len(created) == 1
    # assert created[0].model == "test-model"
    assert created[0].requests


def test_call_workflow_service_requires_configured_llm_provider():
    with pytest.raises(UnsupportedProviderError, match="LLM provider"):
        build_call_workflow_service(
            settings=make_settings(llm_provider="not_configured")
        )


def test_audio_pipeline_runs_through_shared_workflow_service():
    call_service = build_call_service()
    workflow = build_call_workflow_service(
        llm_client=FakeLLMClient(), call_service=call_service
    )
    pipeline = build_audio_processing_pipeline(
        workflow,
        [DiarizedSegment("s0", 0.0, 2.0)],
        asr_provider=FakeASRProvider(),
        language_provider=FakeLanguageProvider(),
    )
    call_service.start_call("call-1")

    result = pipeline.process_audio("call-1", b"audio")

    assert isinstance(result, CallAnalysisResult)
    latest = call_service.get_call("call-1").latest_utterance
    assert latest is not None
    assert latest.speaker_role == SpeakerRole.ICR
    assert latest.languages == ("en",)


def test_audio_pipeline_builds_default_sarvam_providers_from_settings():
    settings = make_settings(
        asr_provider="sarvam",
        language_provider="sarvam",
        sarvam_api_key="test-key",
    )
    workflow = build_call_workflow_service(llm_client=FakeLLMClient())

    pipeline = build_audio_processing_pipeline(
        workflow, [DiarizedSegment("s0", 0.0, 1.0)], settings=settings
    )

    assert isinstance(pipeline, AudioProcessingPipeline)


def test_audio_pipeline_requires_configured_asr_provider():
    workflow = build_call_workflow_service(llm_client=FakeLLMClient())

    with pytest.raises(UnsupportedProviderError, match="ASR provider"):
        build_audio_processing_pipeline(
            workflow,
            [DiarizedSegment("s0", 0.0, 1.0)],
            settings=make_settings(asr_provider="not_configured"),
        )