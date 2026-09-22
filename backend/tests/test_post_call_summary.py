from decimal import Decimal

import pytest

from app.ai.sentiment.provider import SentimentLabel, SentimentResult
from app.ai.summary.provider import PostCallSummaryRequest, SummaryGenerationProvider
from app.domain.complaint_coverage import ComplaintCoverage, ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.post_call_summary import ComplaintSummary, PostCallSummary
from app.domain.service_estimate import EstimatedPart, LabourEstimate, ServiceEstimate
from typing import Any


def make_sentiment() -> SentimentResult:
    return SentimentResult(SentimentLabel.NEUTRAL, 0.6, "Customer was calm throughout.")


def make_complaint_summary(**overrides) -> ComplaintSummary:
    fields: dict[str, Any] = dict(
        category="Turnaround Time",
        description="Delivery delayed by two days.",
        status=ComplaintCoverageStatus.RESOLVED,
        evidence="Customer said the car was late.",
        confidence=0.8,
    )
    fields.update(overrides)
    return ComplaintSummary(**fields)


def make_service_estimate() -> ServiceEstimate:
    return ServiceEstimate(
        service_name="Brake Pad Replacement",
        currency="INR",
        parts=(EstimatedPart("Brake Pad", 2, Decimal("500")),),
        labour=LabourEstimate(1.5, Decimal("400")),
        estimated_duration_hours=2.0,
    )


def make_post_call_summary(**overrides) -> PostCallSummary:
    fields: dict[str, Any] = dict(
        call_id="call-1",
        overall_summary="Customer reported a delayed service and it was resolved.",
        languages=("en", "ta"),
        sentiment=make_sentiment(),
        complaints=(make_complaint_summary(),),
        unresolved_issues=(),
        actions_promised=("Call back tomorrow with an update.",),
        follow_up_required=True,
        customer_summary="Your service was delayed; we've addressed it.",
        service_estimate=make_service_estimate(),
    )
    fields.update(overrides)
    return PostCallSummary(**fields)


# ---- ComplaintSummary ----

def test_complaint_summary_valid():
    summary = make_complaint_summary()
    assert summary.category == "Turnaround Time"
    assert summary.confidence == 0.8


def test_complaint_summary_rejects_unknown_category():
    with pytest.raises(ValueError):
        make_complaint_summary(category="Not A Category")


def test_complaint_summary_rejects_empty_description():
    with pytest.raises(ValueError):
        make_complaint_summary(description="   ")


def test_complaint_summary_rejects_invalid_status_type():
    with pytest.raises(TypeError):
        make_complaint_summary(status="resolved")


def test_complaint_summary_rejects_empty_evidence():
    with pytest.raises(ValueError):
        make_complaint_summary(evidence="")


def test_complaint_summary_rejects_out_of_range_confidence():
    with pytest.raises(ValueError):
        make_complaint_summary(confidence=1.5)


def test_complaint_summary_confidence_optional():
    summary = make_complaint_summary(confidence=None)
    assert summary.confidence is None


# ---- PostCallSummary ----

def test_post_call_summary_valid():
    summary = make_post_call_summary()
    assert summary.call_id == "call-1"
    assert summary.service_estimate is not None


def test_post_call_summary_valid_without_service_estimate():
    summary = make_post_call_summary(service_estimate=None)
    assert summary.service_estimate is None


def test_post_call_summary_rejects_empty_call_id():
    with pytest.raises(ValueError):
        make_post_call_summary(call_id="  ")


def test_post_call_summary_rejects_unsupported_language():
    with pytest.raises(ValueError):
        make_post_call_summary(languages=("en", "fr"))


def test_post_call_summary_rejects_empty_languages():
    with pytest.raises(ValueError):
        make_post_call_summary(languages=())


def test_post_call_summary_rejects_wrong_sentiment_type():
    with pytest.raises(TypeError):
        make_post_call_summary(sentiment="POSITIVE")


def test_post_call_summary_rejects_non_complaint_summary_items():
    with pytest.raises(ValueError):
        make_post_call_summary(complaints=("not a ComplaintSummary",))


def test_post_call_summary_rejects_non_bool_follow_up_required():
    with pytest.raises(TypeError):
        make_post_call_summary(follow_up_required="yes")


def test_post_call_summary_rejects_empty_customer_summary():
    with pytest.raises(ValueError):
        make_post_call_summary(customer_summary="")


def test_post_call_summary_rejects_wrong_service_estimate_type():
    with pytest.raises(TypeError):
        make_post_call_summary(service_estimate="not an estimate")


def test_post_call_summary_rejects_blank_items_in_unresolved_issues():
    with pytest.raises(ValueError):
        make_post_call_summary(unresolved_issues=("valid", "   "))


# ---- SummaryGenerationProvider contract ----

class FakeSummaryProvider(SummaryGenerationProvider):
    def __init__(self, result: PostCallSummary | None):
        self._result = result

    def generate_summary(self, request: PostCallSummaryRequest) -> PostCallSummary | None:
        return self._result


def make_request(**overrides) -> PostCallSummaryRequest:
    fields: dict[str, Any] = dict(
        call_id="call-1",
        conversation=Conversation(call_id="call-1"),
        complaint_coverages=(ComplaintCoverage("Turnaround Time"),),
        sentiment=make_sentiment(),
        service_estimate=None,
    )
    fields.update(overrides)
    return PostCallSummaryRequest(**fields)


def test_provider_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        SummaryGenerationProvider() # type: ignore


def test_fake_provider_returns_post_call_summary():
    expected = make_post_call_summary()
    provider = FakeSummaryProvider(expected)

    result = provider.generate_summary(make_request())

    assert result is expected

def test_post_call_summary_rejects_blank_items_in_actions_promised():
    with pytest.raises(ValueError):
        make_post_call_summary(
            actions_promised=("valid action", "   ")
        )

def test_fake_provider_can_return_none():
    provider = FakeSummaryProvider(None)

    result = provider.generate_summary(make_request())

    assert result is None


def test_request_rejects_empty_call_id():
    with pytest.raises(ValueError):
        make_request(call_id="")


def test_request_rejects_wrong_conversation_type():
    with pytest.raises(TypeError):
        make_request(conversation="not a conversation")


def test_request_rejects_non_complaint_coverage_items():
    with pytest.raises(ValueError):
        make_request(complaint_coverages=("bad item",))