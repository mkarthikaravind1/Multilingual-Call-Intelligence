import pytest

from app.ai.asr.provider import ASRProvider, ASRResult
from app.ai.language.provider import (
    LanguageIdentificationProvider,
    LanguageIdentificationResult,
    LanguageSpan,
)
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.speaker.provider import DiarizedSegment
from app.composition import providers
from app.composition.container import ApplicationServices, build_application_services
from app.composition.providers import UnsupportedProviderError
from app.core.config import Settings
from app.domain.utterance import SpeakerRole
from app.services.audio_processing_pipeline import AudioProcessingPipeline
from app.services.call_workflow_service import CallAnalysisResult, CallWorkflowService


class FakeLLMClient(LLMClient):
    def __init__(self, model: str | None = None) -> None:
        self.model = model

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(text="[]")


class FakeASRProvider(ASRProvider):
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    def transcribe(self, audio: bytes) -> ASRResult:
        return ASRResult(
            transcript="The bill is too high",
            detected_language="en",
            start_time=0.0,
            end_time=2.0,
        )


class FakeLanguageProvider(LanguageIdentificationProvider):
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    def identify(self, text: str) -> LanguageIdentificationResult:
        return LanguageIdentificationResult(languages=[LanguageSpan(language="en")])


def make_settings(**overrides) -> Settings:
    values = {
        "llm_provider": "groq",
        "asr_provider": "sarvam",
        "language_provider": "sarvam",
        "diarization_provider": "scripted",
        "role_provider": "order_based",
        "sarvam_api_key": "test-key",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
def fake_providers(monkeypatch):
    monkeypatch.setattr(providers, "GroqLLMClient", FakeLLMClient)
    monkeypatch.setattr(providers, "SarvamASRProvider", FakeASRProvider)
    monkeypatch.setattr(providers, "SarvamLanguageProvider", FakeLanguageProvider)


def test_build_application_services_returns_wired_services(fake_providers):
    services = build_application_services(make_settings())

    assert isinstance(services, ApplicationServices)
    assert isinstance(services.workflow_service, CallWorkflowService)
    assert isinstance(services.audio_pipeline, AudioProcessingPipeline)


def test_audio_flows_through_settings_selected_providers(fake_providers):
    services = build_application_services(
        make_settings(), diarization_segments=[DiarizedSegment("s0", 0.0, 2.0)]
    )
    services.call_service.start_call("call-1")

    result = services.audio_pipeline.process_audio("call-1", b"audio")

    assert isinstance(result, CallAnalysisResult)
    conversation = services.call_service.get_call("call-1")
    assert conversation.utterance_count == 1
    assert conversation.latest_utterance is not None
    assert conversation.latest_utterance.speaker_role == SpeakerRole.ICR


def test_pipeline_and_workflow_share_call_state(fake_providers):
    services = build_application_services(
        make_settings(), diarization_segments=[DiarizedSegment("s0", 0.0, 2.0)]
    )
    services.call_service.start_call("call-1")

    services.audio_pipeline.process_audio("call-1", b"audio")
    analysis = services.workflow_service.analyze_call("call-1")

    assert analysis.coverage.call_id == "call-1"


@pytest.mark.parametrize(
    "override",
    [
        {"llm_provider": "not_configured"},
        {"asr_provider": "not_configured"},
        {"language_provider": "not_configured"},
        {"diarization_provider": "not_configured"},
        {"role_provider": "not_configured"},
    ],
)
def test_unconfigured_provider_fails_fast(fake_providers, override):
    with pytest.raises(UnsupportedProviderError):
        build_application_services(make_settings(**override))