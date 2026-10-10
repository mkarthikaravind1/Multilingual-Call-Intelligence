"""Reading an LLM's JSON answer, and asking once more when it is unusable:
the shared helper, and the complaint, sentiment, escalation and combined
live requests that use it."""

import json
import logging

import pytest

from app.ai.complaint.llm_provider import LLMComplaintProvider
from app.ai.escalation.llm_provider import LLMEscalationProvider
from app.ai.escalation.provider import EscalationContext
from app.ai.live_analysis.llm_provider import LLMLiveAnalysisProvider
from app.ai.llm.client import LLMClient, LLMRateLimitedError, LLMRequest, LLMResponse
from app.ai.llm.json_answer import RETRY_NOTE, UnusableAnswer, ask_for_json, decode_json
from app.ai.sentiment.llm_provider import LLMSentimentProvider
from app.ai.sentiment.provider import SentimentLabel
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.escalation import EscalationSignalType
from app.domain.utterance import SpeakerRole, Utterance
from app.observability.metrics import LLM_UNUSABLE_ANSWERS
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.conversation_analysis_service import ConversationAnalysisService
from app.services.sentiment_analysis_service import SentimentAnalysisService

MANAGER_LINE = "Sorry is not enough. I want to speak to your manager right now."

COMPLAINTS = [
    {"category": "Cost", "confidence": 0.9, "evidence": "The bill was higher than quoted."}
]
SENTIMENT = {"label": "NEGATIVE", "confidence": 0.9, "evidence": "The customer is angry."}
ESCALATION = {
    "signals": [
        {
            "type": "manager_request",
            "level": "high",
            "description": "Customer wants a manager.",
            "evidence": "I want to speak to your manager right now",
        }
    ]
}
COMBINED = {"complaints": COMPLAINTS, "sentiment": SENTIMENT, "escalation": ESCALATION}


class AnswersInTurn(LLMClient):
    """Gives its answers one per request; an exception among them is raised."""

    def __init__(self, *answers) -> None:
        self._answers = list(answers)
        self.prompts: list[str] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.prompts.append(request.prompt)
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return LLMResponse(text=answer if isinstance(answer, str) else json.dumps(answer))


def _conversation() -> Conversation:
    call = Conversation(call_id="call-1")
    for i, (role, text) in enumerate(
        [
            (SpeakerRole.ICR, "Good morning, how can I help you?"),
            (SpeakerRole.CUSTOMER, "The bill was 14,000 but you quoted 8,000."),
            (SpeakerRole.CUSTOMER, MANAGER_LINE),
        ]
    ):
        call.add_utterance(
            Utterance(
                utterance_id=f"u{i}",
                transcript=text,
                speaker_role=role,
                languages=("en",),
                start_time=float(i),
                end_time=i + 0.5,
            )
        )
    return call


def _counts(task: str) -> tuple[float, float]:
    return (
        LLM_UNUSABLE_ANSWERS.value(task, "recovered"),
        LLM_UNUSABLE_ANSWERS.value(task, "dropped"),
    )


# ---- Reading an answer ----


@pytest.mark.parametrize(
    "text",
    [
        '[{"a": 1}]',
        '```json\n[{"a": 1}]\n```',
        'Here are the complaints:\n[{"a": 1}]',
        '[{"a": 1}]\nLet me know if you need anything else.',
        'Sure.\n```\n[{"a": 1}]\n```',
    ],
)
def test_json_is_read_from_a_fence_or_surrounding_commentary(text):
    assert decode_json(text) == [{"a": 1}]


@pytest.mark.parametrize("text", ["", "no json here", '[{"a": 1}, {"a"', None, 42])
def test_an_answer_without_whole_json_is_unusable(text):
    with pytest.raises(UnusableAnswer):
        decode_json(text)


def test_a_cut_short_answer_is_not_read_as_a_value_inside_it():
    # The object inside is whole, the answer is not.
    with pytest.raises(UnusableAnswer):
        decode_json('{"sentiment": {"label": "NEGATIVE"}, "complaints": [')


# ---- Asking once more ----


def test_a_usable_first_answer_is_not_asked_for_again():
    llm = AnswersInTurn("[1]")
    before = _counts("test")

    assert ask_for_json(llm, LLMRequest(prompt="Q"), decode_json, "test") == [1]

    assert llm.prompts == ["Q"]
    assert _counts("test") == before


def test_an_unusable_answer_is_asked_for_once_more_saying_so(caplog):
    llm = AnswersInTurn("I think the customer is upset", "[1]")
    recovered, dropped = _counts("test")

    with caplog.at_level(logging.WARNING):
        result = ask_for_json(llm, LLMRequest(prompt="Q"), decode_json, "test")

    assert result == [1]
    assert llm.prompts == ["Q", "Q" + RETRY_NOTE]
    assert _counts("test") == (recovered + 1, dropped)
    # The log shows what the model actually said.
    assert "I think the customer is upset" in caplog.text


def test_two_unusable_answers_give_up_without_a_third_request():
    llm = AnswersInTurn("nope", "still nope", "[1]")
    recovered, dropped = _counts("test")

    with pytest.raises(UnusableAnswer):
        ask_for_json(llm, LLMRequest(prompt="Q"), decode_json, "test")

    assert len(llm.prompts) == 2
    assert _counts("test") == (recovered, dropped + 1)


def test_a_failing_request_is_not_retried():
    llm = AnswersInTurn(LLMRateLimitedError("slow down", 5.0), "[1]")

    with pytest.raises(LLMRateLimitedError):
        ask_for_json(llm, LLMRequest(prompt="Q"), decode_json, "test")

    assert len(llm.prompts) == 1


def test_a_rate_limit_on_the_second_request_is_raised():
    llm = AnswersInTurn("nope", LLMRateLimitedError("slow down", 5.0))

    with pytest.raises(LLMRateLimitedError):
        ask_for_json(llm, LLMRequest(prompt="Q"), decode_json, "test")


# ---- Complaints ----


def test_complaints_are_asked_for_again_after_an_unusable_answer():
    llm = AnswersInTurn('[{"category": "Cost", "confid', COMPLAINTS)

    results = LLMComplaintProvider(llm).detect(_conversation())

    assert [r.category for r in results] == ["Cost"]
    assert len(llm.prompts) == 2
    assert llm.prompts[1] == llm.prompts[0] + RETRY_NOTE


def test_two_unusable_complaint_answers_give_no_complaints():
    llm = AnswersInTurn("not json", {"category": "Cost"})

    assert LLMComplaintProvider(llm).detect(_conversation()) == []
    assert len(llm.prompts) == 2


def test_no_complaints_is_an_answer_and_is_not_asked_for_again():
    llm = AnswersInTurn("[]")

    assert LLMComplaintProvider(llm).detect(_conversation()) == []
    assert len(llm.prompts) == 1


def test_a_malformed_item_is_skipped_and_the_rest_kept_without_a_new_request():
    llm = AnswersInTurn(
        [*COMPLAINTS, {"category": "Communication", "confidence": "high", "evidence": "x"}]
    )

    results = LLMComplaintProvider(llm).detect(_conversation())

    assert [r.category for r in results] == ["Cost"]
    assert len(llm.prompts) == 1


def test_an_answer_with_only_malformed_items_is_asked_for_again():
    llm = AnswersInTurn([{"category": "Cost", "confidence": "high", "evidence": "x"}], COMPLAINTS)

    results = LLMComplaintProvider(llm).detect(_conversation())

    assert [r.category for r in results] == ["Cost"]
    assert len(llm.prompts) == 2


def test_a_category_reported_twice_becomes_one_complaint():
    llm = AnswersInTurn(
        [
            {"category": "Cost", "confidence": 0.6, "evidence": "Bill too high.", "probed": True},
            {"category": "Communication", "confidence": 0.7, "evidence": "Nobody called."},
            {"category": "cost", "confidence": 0.9, "evidence": "Charged 14,000, quoted 8,000."},
        ]
    )

    results = LLMComplaintProvider(llm).detect(_conversation())

    assert [r.category for r in results] == ["Cost", "Communication"]
    cost = results[0]
    # The more confident report, asked about if either says so.
    assert (cost.confidence, cost.evidence, cost.probed) == (
        0.9,
        "Charged 14,000, quoted 8,000.",
        True,
    )
    assert len(llm.prompts) == 1


# ---- Sentiment ----


def test_sentiment_is_asked_for_again_after_an_unusable_answer():
    llm = AnswersInTurn("The customer sounds negative.", SENTIMENT)

    result = LLMSentimentProvider(llm).analyze(_conversation())

    assert result.label is SentimentLabel.NEGATIVE
    assert len(llm.prompts) == 2


def test_two_unusable_sentiment_answers_give_the_undetermined_result():
    llm = AnswersInTurn("not json", {"label": "NEGATIVE"})

    result = LLMSentimentProvider(llm).analyze(_conversation())

    assert (result.label, result.confidence) == (SentimentLabel.NEUTRAL, 0.0)
    assert len(llm.prompts) == 2


def test_a_sentiment_label_in_another_case_is_accepted():
    llm = AnswersInTurn({**SENTIMENT, "label": " Frustrated "})

    result = LLMSentimentProvider(llm).analyze(_conversation())

    assert result.label is SentimentLabel.FRUSTRATED
    assert len(llm.prompts) == 1


# ---- Escalation ----


def _escalation_context() -> EscalationContext:
    return EscalationContext(_conversation(), ConversationCoverage(call_id="call-1"), None)


def test_escalation_is_asked_for_again_after_an_unusable_answer():
    llm = AnswersInTurn('{"signals": [{"type": "manager_request", "lev', ESCALATION)

    assessment = LLMEscalationProvider(llm).assess(_escalation_context())

    assert [s.signal_type for s in assessment.signals] == [EscalationSignalType.MANAGER_REQUEST]
    assert len(llm.prompts) == 2


def test_two_unusable_escalation_answers_give_no_signals():
    llm = AnswersInTurn("not json", {"signals": "none"})

    assert LLMEscalationProvider(llm).assess(_escalation_context()).signals == ()
    assert len(llm.prompts) == 2


# ---- The combined live request ----


def _live_service(llm) -> ConversationAnalysisService:
    complaints, sentiment = LLMComplaintProvider(llm), LLMSentimentProvider(llm)
    return ConversationAnalysisService(
        ComplaintAnalysisService(complaints),
        SentimentAnalysisService(sentiment),
        live_analyzer=LLMLiveAnalysisProvider(
            llm, complaints, sentiment, LLMEscalationProvider(llm)
        ),
    )


def test_an_unreadable_combined_answer_is_asked_for_again_as_one_request():
    llm = AnswersInTurn('{"complaints": [{"category": "Cost"', COMBINED)

    result = _live_service(llm).analyze(_conversation(), ConversationCoverage("call-1"), live=True)

    # Two combined requests, and no separate ones.
    assert len(llm.prompts) == 2
    assert all("TASK 1 - complaints" in prompt for prompt in llm.prompts)
    assert {c.category for c in result.coverage.complaints} == {"Cost"}
    assert result.sentiment.label is SentimentLabel.NEGATIVE
    assert result.escalation_signals


def test_a_combined_answer_without_any_section_is_asked_for_again():
    llm = AnswersInTurn({"result": "ok"}, COMBINED)

    result = _live_service(llm).analyze(_conversation(), ConversationCoverage("call-1"), live=True)

    assert len(llm.prompts) == 2
    assert result.sentiment.label is SentimentLabel.NEGATIVE


def test_two_unreadable_combined_answers_fall_back_to_separate_requests():
    llm = AnswersInTurn("not json", "still not json", COMPLAINTS, SENTIMENT)

    result = _live_service(llm).analyze(_conversation(), ConversationCoverage("call-1"), live=True)

    assert len(llm.prompts) == 4
    assert "TASK 1" not in llm.prompts[2] and "TASK 1" not in llm.prompts[3]
    assert {c.category for c in result.coverage.complaints} == {"Cost"}
    assert result.sentiment.label is SentimentLabel.NEGATIVE
    # The escalation detector asks on its own.
    assert result.escalation_signals is None


def test_one_bad_section_is_asked_for_alone_not_the_whole_answer_again():
    llm = AnswersInTurn({**COMBINED, "sentiment": "negative"}, SENTIMENT)

    result = _live_service(llm).analyze(_conversation(), ConversationCoverage("call-1"), live=True)

    assert len(llm.prompts) == 2
    assert "TASK 1" not in llm.prompts[1]
    assert {c.category for c in result.coverage.complaints} == {"Cost"}
    assert result.sentiment.label is SentimentLabel.NEGATIVE
