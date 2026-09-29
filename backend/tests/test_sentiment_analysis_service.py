from typing import Any

import pytest

from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
)
from app.domain.active_improvement import ActiveImprovement, ActiveImprovementStatus
from app.domain.active_improvement_repository import InMemoryActiveImprovementRepository
from app.domain.conversation import Conversation
from app.domain.improvement_candidate import ImprovementSpecification
from app.domain.learning_evidence import LearningComponent
from app.services.runtime_improvement_service import (
    ComponentLearning,
    RuntimeImprovementService,
)
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


# ---- Approved learning improvements at runtime ----

class LearningAwareSentimentProvider(SentimentAnalysisProvider):
    def __init__(self, result: SentimentResult) -> None:
        self.result = result
        self.received_context: tuple | None = None

    def analyze(self, conversation, learning_context=()):
        self.received_context = learning_context
        return self.result


class RecordingUsage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, str]] = []

    def record_component_usage(self, call_id, contexts, output_value):
        self.calls.append((call_id, contexts, output_value))


def _learning(component: LearningComponent, recorder: RecordingUsage) -> ComponentLearning:
    repository = InMemoryActiveImprovementRepository()
    repository.save(
        ActiveImprovement(
            improvement_id="improvement-1",
            candidate_id="candidate-1",
            component=component,
            specification=ImprovementSpecification(
                component=component,
                current_behavior="Reviewers corrected 'NEUTRAL' to 'NEGATIVE'.",
                proposed_behavior="Weigh unresolved delays as negative.",
                reason="Recurred 2 times.",
            ),
            status=ActiveImprovementStatus.ACTIVE,
            activated_at=100.0,
        )
    )
    return ComponentLearning(
        LearningComponent.SENTIMENT_ANALYSIS, RuntimeImprovementService(repository), recorder
    )


def test_active_sentiment_improvements_reach_the_provider_and_usage_is_recorded():
    provider = LearningAwareSentimentProvider(_result(SentimentLabel.NEGATIVE))
    recorder = RecordingUsage()
    service = SentimentAnalysisService(
        provider, _learning(LearningComponent.SENTIMENT_ANALYSIS, recorder)
    )

    result = service.analyze(_conversation())

    assert result.label is SentimentLabel.NEGATIVE
    assert provider.received_context is not None
    assert [c.improvement_id for c in provider.received_context] == ["improvement-1"]
    assert recorder.calls == [("call-1", provider.received_context, "NEGATIVE")]


def test_sentiment_without_matching_improvements_uses_one_argument_provider():
    provider = FakeSentimentProvider(result=_result())
    recorder = RecordingUsage()
    service = SentimentAnalysisService(
        provider, _learning(LearningComponent.NEXT_QUESTION, recorder)
    )

    service.analyze(_conversation())

    assert len(provider.calls) == 1
    assert recorder.calls == []