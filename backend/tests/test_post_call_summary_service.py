from typing import Any

import pytest

from app.ai.sentiment.provider import SentimentLabel, SentimentResult
from app.ai.summary.provider import PostCallSummaryRequest, SummaryGenerationProvider
from app.domain.complaint_coverage import ComplaintCoverage, ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.post_call_summary import ComplaintSummary, PostCallSummary
from app.services.post_call_summary_service import PostCallSummaryService


def make_sentiment() -> SentimentResult:
    return SentimentResult(SentimentLabel.NEUTRAL, 0.6, "Customer was calm throughout.")


def make_post_call_summary(call_id: str = "call-1") -> PostCallSummary:
    return PostCallSummary(
        call_id=call_id,
        overall_summary="Customer reported a delayed service and it was resolved.",
        languages=("en", "ta"),
        sentiment=make_sentiment(),
        complaints=(
            ComplaintSummary(
                category="Turnaround Time",
                description="Delivery delayed by two days.",
                status=ComplaintCoverageStatus.RESOLVED,
                evidence="Customer said the car was late.",
                confidence=0.8,
            ),
        ),
        unresolved_issues=(),
        actions_promised=("Call back tomorrow with an update.",),
        follow_up_required=True,
        customer_summary="Your service was delayed; we've addressed it.",
        service_estimate=None,
    )


def make_request(call_id: str = "call-1", conversation_call_id: str = "call-1") -> PostCallSummaryRequest:
    fields: dict[str, Any] = dict(
        call_id=call_id,
        conversation=Conversation(call_id=conversation_call_id),
        complaint_coverages=(ComplaintCoverage("Turnaround Time"),),
        sentiment=make_sentiment(),
        service_estimate=None,
    )
    return PostCallSummaryRequest(**fields)


class FakeSummaryProvider(SummaryGenerationProvider):
    def __init__(self, result: PostCallSummary | None = None, exception: Exception | None = None):
        self._result = result
        self._exception = exception
        self.received_request: PostCallSummaryRequest | None = None

    def generate_summary(self, request: PostCallSummaryRequest) -> PostCallSummary | None:
        self.received_request = request
        if self._exception is not None:
            raise self._exception
        return self._result


def test_service_returns_valid_summary_from_provider():
    summary = make_post_call_summary()
    provider = FakeSummaryProvider(result=summary)
    service = PostCallSummaryService(provider)

    result = service.generate_summary(make_request())

    assert result is summary
    assert provider.received_request is not None


def test_service_allows_provider_returning_none():
    provider = FakeSummaryProvider(result=None)
    service = PostCallSummaryService(provider)

    result = service.generate_summary(make_request())

    assert result is None


def test_service_rejects_invalid_provider_result_type():
    provider = FakeSummaryProvider(result="not a PostCallSummary")  # type: ignore[arg-type]
    service = PostCallSummaryService(provider)

    with pytest.raises(TypeError):
        service.generate_summary(make_request())


def test_service_rejects_call_id_mismatch():
    provider = FakeSummaryProvider(result=make_post_call_summary())
    service = PostCallSummaryService(provider)

    with pytest.raises(ValueError):
        service.generate_summary(make_request(call_id="call-1", conversation_call_id="call-2"))

    assert provider.received_request is None  # provider must not be called on mismatch


def test_service_lets_provider_exceptions_propagate():
    provider = FakeSummaryProvider(exception=RuntimeError("provider failed"))
    service = PostCallSummaryService(provider)

    with pytest.raises(RuntimeError):
        service.generate_summary(make_request())