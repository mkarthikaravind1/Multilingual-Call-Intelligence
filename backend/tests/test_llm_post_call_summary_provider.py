import json
from decimal import Decimal

import pytest

from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.sentiment.provider import SentimentLabel, SentimentResult
from app.ai.summary.llm_provider import LLMPostCallSummaryProvider
from app.ai.summary.provider import PostCallSummaryRequest
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.post_call_summary import PostCallSummary
from app.domain.service_estimate import LabourEstimate, ServiceEstimate
from app.domain.utterance import SpeakerRole, Utterance

CALL_ID = "call-1"

VALID_PAYLOAD = {
    "overall_summary": "Customer reported a turnaround time delay.",
    "complaints": [
        {
            "category": "Turnaround Time",
            "description": "Vehicle was not ready on time.",
            "status": "detected",
            "evidence": "The vehicle was not ready on time.",
            "confidence": 0.85,
        }
    ],
    "unresolved_issues": ["Vehicle was not ready on time."],
    "actions_promised": ["Technician will call back tomorrow."],
    "follow_up_required": True,
    "customer_summary": "Thanks for calling, we'll follow up on the delay.",
}


class FakeLLMClient(LLMClient):
    def __init__(self, response_text: str = "", error: Exception | None = None) -> None:
        self._response_text = response_text
        self._error = error
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return LLMResponse(text=self._response_text)


def _conversation(call_id: str = CALL_ID) -> Conversation:
    conversation = Conversation(call_id=call_id)
    conversation.add_utterance(
        Utterance(
            utterance_id="1",
            transcript="The vehicle was not ready on time.",
            speaker_role=SpeakerRole.CUSTOMER,
            languages=("en",),
            start_time=0.0,
            end_time=4.0,
        )
    )
    return conversation


def _sentiment() -> SentimentResult:
    return SentimentResult(SentimentLabel.NEGATIVE, 0.9, "Customer reported a delay.")


def _service_estimate() -> ServiceEstimate:
    return ServiceEstimate(
        service_name="Oil Change",
        currency="INR",
        parts=(),
        labour=LabourEstimate(hours=1.0, hourly_rate=Decimal("500")),
        estimated_duration_hours=1.0,
    )


def _request(
    conversation: Conversation | None = None,
    complaint_coverages: tuple = (),
    sentiment: SentimentResult | None = None,
    service_estimate: ServiceEstimate | None = None,
) -> PostCallSummaryRequest:
    conversation = conversation or _conversation()
    return PostCallSummaryRequest(
        call_id=conversation.call_id,
        conversation=conversation,
        complaint_coverages=complaint_coverages,
        sentiment=sentiment or _sentiment(),
        service_estimate=service_estimate,
    )


def test_generates_summary_from_valid_llm_response():
    provider = LLMPostCallSummaryProvider(FakeLLMClient(json.dumps(VALID_PAYLOAD)))
    request = _request()

    summary = provider.generate_summary(request)

    assert isinstance(summary, PostCallSummary)
    assert summary.call_id == request.call_id
    assert summary.languages == ("en",)
    assert summary.sentiment is request.sentiment
    assert summary.overall_summary == VALID_PAYLOAD["overall_summary"]
    assert summary.customer_summary == VALID_PAYLOAD["customer_summary"]
    assert summary.follow_up_required is True
    assert summary.actions_promised == ("Technician will call back tomorrow.",)
    assert len(summary.complaints) == 1
    assert summary.complaints[0].category == "Turnaround Time"
    assert summary.complaints[0].status == ComplaintCoverageStatus.DETECTED
    assert summary.complaints[0].confidence == 0.85
    assert summary.service_estimate is None


def test_preserves_service_estimate_from_request():
    estimate = _service_estimate()
    provider = LLMPostCallSummaryProvider(FakeLLMClient(json.dumps(VALID_PAYLOAD)))

    summary = provider.generate_summary(_request(service_estimate=estimate))

    assert summary is not None
    assert summary.service_estimate is estimate


def test_returns_none_when_llm_returns_invalid_json():
    provider = LLMPostCallSummaryProvider(FakeLLMClient("not json"))

    assert provider.generate_summary(_request()) is None


def test_returns_none_when_response_is_json_but_not_an_object():
    provider = LLMPostCallSummaryProvider(FakeLLMClient(json.dumps(["a", "list"])))

    assert provider.generate_summary(_request()) is None


def test_returns_none_when_required_key_is_missing():
    payload = {key: value for key, value in VALID_PAYLOAD.items() if key != "customer_summary"}
    provider = LLMPostCallSummaryProvider(FakeLLMClient(json.dumps(payload)))

    assert provider.generate_summary(_request()) is None


def test_returns_none_when_complaint_status_is_invalid():
    payload = dict(VALID_PAYLOAD)
    payload["complaints"] = [{**VALID_PAYLOAD["complaints"][0], "status": "not_a_status"}]
    provider = LLMPostCallSummaryProvider(FakeLLMClient(json.dumps(payload)))

    assert provider.generate_summary(_request()) is None


def test_returns_none_when_complaint_category_is_unsupported():
    payload = dict(VALID_PAYLOAD)
    payload["complaints"] = [{**VALID_PAYLOAD["complaints"][0], "category": "Not A Real Category"}]
    provider = LLMPostCallSummaryProvider(FakeLLMClient(json.dumps(payload)))

    assert provider.generate_summary(_request()) is None


def test_returns_none_when_follow_up_required_is_not_boolean():
    payload = dict(VALID_PAYLOAD)
    payload["follow_up_required"] = "yes"
    provider = LLMPostCallSummaryProvider(FakeLLMClient(json.dumps(payload)))

    assert provider.generate_summary(_request()) is None


def test_returns_none_when_unresolved_issues_is_not_a_string_list():
    payload = dict(VALID_PAYLOAD)
    payload["unresolved_issues"] = [1, 2, 3]
    provider = LLMPostCallSummaryProvider(FakeLLMClient(json.dumps(payload)))

    assert provider.generate_summary(_request()) is None


def test_returns_none_when_llm_client_raises():
    provider = LLMPostCallSummaryProvider(FakeLLMClient(error=RuntimeError("boom")))

    assert provider.generate_summary(_request()) is None


def test_handles_empty_complaints_list():
    payload = dict(VALID_PAYLOAD)
    payload["complaints"] = []
    payload["unresolved_issues"] = []
    provider = LLMPostCallSummaryProvider(FakeLLMClient(json.dumps(payload)))

    summary = provider.generate_summary(_request())

    assert summary is not None
    assert summary.complaints == ()
    assert summary.unresolved_issues == ()


def test_prompt_includes_call_id_and_transcript():
    fake_client = FakeLLMClient(json.dumps(VALID_PAYLOAD))
    provider = LLMPostCallSummaryProvider(fake_client)
    request = _request()

    provider.generate_summary(request)

    assert len(fake_client.requests) == 1
    prompt = fake_client.requests[0].prompt
    assert request.call_id in prompt
    assert "not ready on time" in prompt.lower()