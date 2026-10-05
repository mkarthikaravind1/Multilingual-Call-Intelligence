"""The call's service estimate: every service that came up in the call,
priced from the price list and added up, kept until the call ends."""

from decimal import Decimal

from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.domain.service_estimate import (
    CallServiceEstimate,
    call_estimate_from_json,
    call_estimate_to_json,
)
from app.domain.utterance import SpeakerRole, Utterance
from app.estimation.default_pricing import DEFAULT_PRICING_CONFIG
from app.estimation.detection import KeywordServiceDetector, LLMServiceDetector
from app.estimation.rule_based_provider import RuleBasedEstimationProvider
from app.services.estimation_service import EstimationService


def line(text: str, role: SpeakerRole = SpeakerRole.CUSTOMER, index: int = 0) -> Utterance:
    return Utterance(
        utterance_id=str(index),
        transcript=text,
        speaker_role=role,
        languages=("en",),
        start_time=float(index),
        end_time=float(index) + 1,
    )


def call(*texts: str) -> list[Utterance]:
    roles = (SpeakerRole.ICR, SpeakerRole.CUSTOMER)
    return [line(text, roles[i % 2], i) for i, text in enumerate(texts)]


def service(detector=None) -> EstimationService:
    return EstimationService(
        RuleBasedEstimationProvider(DEFAULT_PRICING_CONFIG), DEFAULT_PRICING_CONFIG, detector
    )


class FakeLLM(LLMClient):
    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.prompts.append(request.prompt)
        if isinstance(self.reply, Exception):
            raise self.reply
        return LLMResponse(self.reply)


# ---- keywords ----

def test_estimate_stays_after_lines_without_a_service():
    estimate = service().estimate_call(
        call("How can I help?", "My brakes are squeaking", "Okay sir, noted", "Thank you")
    )

    assert estimate is not None
    assert estimate.service_names == ("Brake Pad Replacement",)
    assert estimate.estimated_cost == Decimal("3700")


def test_services_add_up_as_they_come_up():
    estimate = service().estimate_call(
        call("Hello", "My brakes are squeaking", "Okay", "Also the battery is weak")
    )

    assert estimate.service_names == ("Brake Pad Replacement", "Battery Replacement")
    assert estimate.parts_cost == Decimal("8300")
    assert estimate.labour_cost == Decimal("1200")
    assert estimate.estimated_cost == Decimal("9500")
    assert estimate.estimated_duration_hours == 4.0


def test_a_service_mentioned_twice_is_charged_once():
    estimate = service().estimate_call(call("brake noise", "the brake again", "brake pads please"))

    assert estimate.service_names == ("Brake Pad Replacement",)


def test_general_service_covers_the_oil_change():
    estimate = service().estimate_call(call("I want an oil change", "and a general service too"))

    assert estimate.service_names == ("General Service",)
    assert estimate.estimated_cost == Decimal("4800")


def test_no_service_no_estimate():
    assert service().estimate_call(call("Hello", "The advisor was rude")) is None
    assert service().estimate_call([]) is None


# ---- LLM ----

def test_llm_detector_follows_the_conversation():
    llm = FakeLLM('{"services": ["Brake Pad Replacement"]}')
    estimate = service(LLMServiceDetector(llm, DEFAULT_PRICING_CONFIG)).estimate_call(
        call(
            "How can I help?",
            "My brakes squeak",
            "Shall we check the battery?",
            "No, the battery is fine",
        )
    )

    # The LLM understood "the battery is fine"; keywords would add it.
    assert estimate.service_names == ("Brake Pad Replacement",)
    assert "Battery Replacement" in llm.prompts[0]
    assert "CUSTOMER: No, the battery is fine" in llm.prompts[0]


def test_llm_names_outside_the_price_list_are_ignored():
    llm = FakeLLM('Sure! {"services": ["Battery Replacement", "Engine Overhaul", 7]}')
    estimate = service(LLMServiceDetector(llm, DEFAULT_PRICING_CONFIG)).estimate_call(
        call("the car will not start")
    )

    assert estimate.service_names == ("Battery Replacement",)
    assert estimate.estimated_cost == Decimal("5800")  # from the price list


def test_llm_failure_falls_back_to_the_keywords():
    llm = FakeLLM(RuntimeError("429 rate limited"))
    estimate = service(LLMServiceDetector(llm, DEFAULT_PRICING_CONFIG)).estimate_call(
        call("my battery is dead")
    )

    assert estimate.service_names == ("Battery Replacement",)


def test_unreadable_llm_reply_falls_back_to_the_keywords():
    llm = FakeLLM("I think it is the brakes")
    estimate = service(LLMServiceDetector(llm, DEFAULT_PRICING_CONFIG)).estimate_call(
        call("brake noise")
    )

    assert estimate.service_names == ("Brake Pad Replacement",)


def test_llm_saying_no_services_means_no_estimate():
    llm = FakeLLM('{"services": []}')
    detector = LLMServiceDetector(llm, DEFAULT_PRICING_CONFIG, KeywordServiceDetector(DEFAULT_PRICING_CONFIG))

    assert service(detector).estimate_call(call("no need for a brake check")) is None


# ---- storage ----

def test_estimate_round_trips_through_json():
    estimate = service().estimate_call(call("brakes", "battery"))

    assert call_estimate_from_json(call_estimate_to_json(estimate)) == estimate


def test_estimates_stored_before_reads_as_one_service():
    legacy = {
        "service_name": "Oil Change",
        "currency": "INR",
        "parts": [{"name": "Oil filter", "quantity": 1, "unit_price": "350"}],
        "labour": {"hours": 0.5, "hourly_rate": "600"},
        "estimated_duration_hours": 1.0,
    }

    estimate = call_estimate_from_json(legacy)

    assert isinstance(estimate, CallServiceEstimate)
    assert estimate.service_names == ("Oil Change",)
    assert estimate.estimated_cost == Decimal("650")
