import pytest

from app.ai.sentiment.provider import (
    SentimentLabel,
    SentimentResult,
)
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.services.conversation_analysis_service import (
    ConversationAnalysisResult,
    ConversationAnalysisService,
)


class FakeComplaintService:
    def __init__(self, coverage: ConversationCoverage) -> None:
        self.coverage = coverage
        self.calls: list[
            tuple[Conversation, ConversationCoverage]
        ] = []

    def analyze(
        self,
        conversation: Conversation,
        coverage: ConversationCoverage,
    ) -> ConversationCoverage:
        self.calls.append((conversation, coverage))
        return self.coverage


class FakeSentimentService:
    def __init__(self, result: SentimentResult) -> None:
        self.result = result
        self.calls: list[Conversation] = []

    def analyze(
        self,
        conversation: Conversation,
    ) -> SentimentResult:
        self.calls.append(conversation)
        return self.result


def _conversation(call_id: str = "call-1") -> Conversation:
    return Conversation(call_id=call_id)


def _coverage(call_id: str = "call-1") -> ConversationCoverage:
    return ConversationCoverage(call_id=call_id)


def _sentiment() -> SentimentResult:
    return SentimentResult(
        label=SentimentLabel.NEGATIVE,
        confidence=0.9,
        evidence="The customer reported a delayed service.",
    )


def test_analyze_runs_complaint_and_sentiment_services() -> None:
    conversation = _conversation()
    coverage = _coverage()

    complaint_service = FakeComplaintService(coverage)
    sentiment_service = FakeSentimentService(_sentiment())

    service = ConversationAnalysisService(
        complaint_service=complaint_service,
        sentiment_service=sentiment_service,
    )

    result = service.analyze(conversation, coverage)

    assert isinstance(result, ConversationAnalysisResult)
    assert result.coverage is coverage
    assert result.sentiment == _sentiment()


def test_same_conversation_is_passed_to_both_services() -> None:
    conversation = _conversation()
    coverage = _coverage()

    complaint_service = FakeComplaintService(coverage)
    sentiment_service = FakeSentimentService(_sentiment())

    service = ConversationAnalysisService(
        complaint_service,
        sentiment_service,
    )

    service.analyze(conversation, coverage)

    assert complaint_service.calls[0][0] is conversation
    assert sentiment_service.calls[0] is conversation


def test_same_coverage_is_passed_to_complaint_service() -> None:
    conversation = _conversation()
    coverage = _coverage()

    complaint_service = FakeComplaintService(coverage)
    sentiment_service = FakeSentimentService(_sentiment())

    service = ConversationAnalysisService(
        complaint_service,
        sentiment_service,
    )

    service.analyze(conversation, coverage)

    assert complaint_service.calls[0][1] is coverage


def test_mismatched_call_ids_are_rejected() -> None:
    conversation = _conversation("call-1")
    coverage = _coverage("call-2")

    complaint_service = FakeComplaintService(coverage)
    sentiment_service = FakeSentimentService(_sentiment())

    service = ConversationAnalysisService(
        complaint_service,
        sentiment_service,
    )

    with pytest.raises(ValueError, match="call_id"):
        service.analyze(conversation, coverage)


def test_services_are_called_once() -> None:
    conversation = _conversation()
    coverage = _coverage()

    complaint_service = FakeComplaintService(coverage)
    sentiment_service = FakeSentimentService(_sentiment())

    service = ConversationAnalysisService(
        complaint_service,
        sentiment_service,
    )

    service.analyze(conversation, coverage)

    assert len(complaint_service.calls) == 1
    assert len(sentiment_service.calls) == 1