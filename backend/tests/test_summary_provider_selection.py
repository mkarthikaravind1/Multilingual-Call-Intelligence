import pytest

from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.summary.llm_provider import LLMPostCallSummaryProvider
from app.ai.summary.rule_based_provider import RuleBasedSummaryProvider
from app.composition.providers import UnsupportedProviderError, create_summary_provider
from app.core.config import Settings


class FakeLLMClient(LLMClient):
    """Never actually called in these tests — selection shouldn't invoke the client."""

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("LLMClient.complete should not be called during provider selection.")


def test_summary_provider_setting_defaults_to_rule_based():
    assert Settings().summary_provider == "rule_based"


def test_create_summary_provider_returns_rule_based_provider():
    provider = create_summary_provider(settings=Settings(summary_provider="rule_based"))

    assert isinstance(provider, RuleBasedSummaryProvider)


def test_create_summary_provider_is_case_insensitive():
    provider = create_summary_provider(settings=Settings(summary_provider="RULE_BASED"))

    assert isinstance(provider, RuleBasedSummaryProvider)


def test_create_summary_provider_returns_llm_provider_when_configured():
    fake_client = FakeLLMClient()

    provider = create_summary_provider(
        llm_client=fake_client, settings=Settings(summary_provider="llm")
    )

    assert isinstance(provider, LLMPostCallSummaryProvider)


def test_create_summary_provider_raises_for_unknown_provider():
    with pytest.raises(UnsupportedProviderError):
        create_summary_provider(settings=Settings(summary_provider="not_a_real_provider"))