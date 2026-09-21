import pytest

from app.ai.complaint.llm_provider import LLMComplaintProvider
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.sentiment.llm_provider import LLMSentimentProvider
from app.ai.speaker.order_based_role_provider import (
    OrderBasedRoleIdentificationProvider,
)
from app.ai.speaker.provider import DiarizedSegment, SpeakerRole
from app.ai.speaker.scripted_diarization_provider import ScriptedDiarizationProvider
from app.ai.speaker.static_role_provider import StaticRoleIdentificationProvider
from app.composition.providers import (
    UnsupportedProviderError,
    create_complaint_provider,
    create_diarization_provider,
    create_role_provider,
    create_sentiment_provider,
)
from app.core.config import Settings


class FakeLLMClient(LLMClient):
    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(text="[]")


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("builder", "expected_type"),
    [
        (create_complaint_provider, LLMComplaintProvider),
        (create_sentiment_provider, LLMSentimentProvider),
    ],
)
def test_llm_backed_factories_use_injected_client(builder, expected_type):
    assert isinstance(builder(FakeLLMClient()), expected_type)


@pytest.mark.parametrize(
    "builder", [create_complaint_provider, create_sentiment_provider]
)
def test_llm_backed_factories_reject_unconfigured_llm_provider(builder):
    with pytest.raises(UnsupportedProviderError):
                builder(settings=make_settings(llm_provider="not_configured"))


def test_create_diarization_provider_returns_scripted_provider():
    segments = [DiarizedSegment("s0", 0.0, 1.0), DiarizedSegment("s1", 1.0, 2.0)]
    settings = make_settings(diarization_provider="scripted")

    provider = create_diarization_provider(segments, settings)

    assert isinstance(provider, ScriptedDiarizationProvider)
    assert provider.diarize(b"audio") == segments


def test_create_diarization_provider_rejects_unconfigured_provider():
    with pytest.raises(UnsupportedProviderError, match="diarization provider"):
        create_diarization_provider(
            [], make_settings(diarization_provider="not_configured")
        )


def test_create_role_provider_order_based():
    provider = create_role_provider(make_settings(role_provider="order_based"))

    assignments = provider.identify_roles(
        [DiarizedSegment("s0", 0.0, 1.0), DiarizedSegment("s1", 1.0, 2.0)]
    )

    assert isinstance(provider, OrderBasedRoleIdentificationProvider)
    assert [a.role for a in assignments] == [SpeakerRole.ICR, SpeakerRole.CUSTOMER]


def test_create_role_provider_static_uses_mapping():
    provider = create_role_provider(
        make_settings(role_provider="static"),
        role_by_speaker={"s0": SpeakerRole.CUSTOMER},
    )

    assignments = provider.identify_roles([DiarizedSegment("s0", 0.0, 1.0)])

    assert isinstance(provider, StaticRoleIdentificationProvider)
    assert assignments[0].role == SpeakerRole.CUSTOMER


def test_create_role_provider_static_requires_mapping():
    with pytest.raises(ValueError, match="role_by_speaker"):
        create_role_provider(make_settings(role_provider="static"))


def test_create_role_provider_rejects_unconfigured_provider():
    with pytest.raises(UnsupportedProviderError, match="role provider"):
        create_role_provider(make_settings(role_provider="not_configured"))