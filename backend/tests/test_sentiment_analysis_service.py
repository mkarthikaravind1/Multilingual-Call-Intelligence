from typing import Any

import pytest

from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
)
from app.domain.conversation import Conversation
from app.services.sentiment_analysis_service import SentimentAnalysisService


class FakeSentimentProvider(SentimentAnalysisProvider):
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[Conversation] = []

    def analyze(self, conversation: Conversation) -> SentimentResult:
        self.calls.append(conversation)
        if self.error is not None:
            raise self.error
        return self.result


def _conversation() -> Conversation:
    return Conversation(call_id="call-1")


def _result(label: SentimentLabel = SentimentLabel.NEGATIVE) -> SentimentResult:
    return SentimentResult(label, 0.9, "Evidence from the conversation.")


def test_service_delegates_to_provider():
    provider = FakeSentimentProvider(result=_result())

    SentimentAnalysisService(provider).analyze(_conversation())

    assert len(provider.calls) == 1


def test_exact_conversation_object_is_passed_to_provider():
    provider = FakeSentimentProvider(result=_result())
    conversation = _conversation()

    SentimentAnalysisService(provider).analyze(conversation)

    assert provider.calls[0] is conversation


def test_provider_result_is_returned_unchanged():
    expected = _result()
    provider = FakeSentimentProvider(result=expected)

    result = SentimentAnalysisService(provider).analyze(_conversation())

    assert result is expected


@pytest.mark.parametrize(
    "label", [SentimentLabel.POSITIVE, SentimentLabel.NEUTRAL, SentimentLabel.NEGATIVE]
)
def test_each_sentiment_label_is_returned(label):
    expected = _result(label)
    provider = FakeSentimentProvider(result=expected)

    result = SentimentAnalysisService(provider).analyze(_conversation())

    assert result.label is label
    assert result == expected


def test_provider_exception_is_not_swallowed():
    provider = FakeSentimentProvider(error=RuntimeError("provider failed"))

    with pytest.raises(RuntimeError, match="provider failed"):
        SentimentAnalysisService(provider).analyze(_conversation())


@pytest.mark.parametrize(
    "invalid",
    [None, "NEGATIVE", SentimentLabel.NEGATIVE, {"label": "NEGATIVE"}, 0.9],
)
def test_non_sentiment_result_raises_type_error(invalid):
    provider = FakeSentimentProvider(result=invalid)

    with pytest.raises(TypeError, match="SentimentResult"):
        SentimentAnalysisService(provider).analyze(_conversation())