"""One LLM request for a live call's complaints, sentiment and escalation,
with each part asked separately when its answer is unusable."""

import json

import pytest

from app.ai.complaint.llm_provider import LLMComplaintProvider
from app.ai.escalation.llm_provider import (
    HybridEscalationProvider,
    LLMEscalationProvider,
)
from app.ai.escalation.rule_based_provider import RuleBasedEscalationProvider
from app.ai.live_analysis.llm_provider import LLMLiveAnalysisProvider
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.sentiment.llm_provider import LLMSentimentProvider
from app.ai.sentiment.provider import SentimentLabel
from app.api.wiring import _build_live_analyzer
from app.core.config import Settings
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.escalation import EscalationSignalType
from app.domain.utterance import SpeakerRole, Utterance
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.conversation_analysis_service import ConversationAnalysisService
from app.services.escalation_repository import InMemoryEscalationRepository
from app.services.escalation_service import EscalationService
from app.services.sentiment_analysis_service import SentimentAnalysisService

MANAGER_LINE = "Sorry is not enough. I want to speak to your manager right now."

COMBINED = {
    "complaints": [
        {"category": "Cost", "confidence": 0.9, "evidence": "The bill was higher than quoted."},
        {"category": "Staff Behaviour", "confidence": 0.8, "evidence": "The advisor was rude."},
    ],
    "sentiment": {"label": "NEGATIVE", "confidence": 0.9, "evidence": "The customer is angry."},
    "escalation": {
        "signals": [
            {
                "type": "manager_request",
                "level": "high",
                "description": "Customer wants a manager.",
                "evidence": "I want to speak to your manager right now",
            }
        ]
    },
}

SEPARATE_COMPLAINTS = [{"category": "Cost", "confidence": 0.7, "evidence": "Bill too high."}]
SEPARATE_SENTIMENT = {"label": "NEUTRAL", "confidence": 0.6, "evidence": "Calm."}


class ScriptedLLM(LLMClient):
    """Answers the combined request with `combined` and each separate
    request with its own answer; records every prompt."""

    def __init__(self, combined) -> None:
        self.combined = combined
        self.prompts: list[str] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.prompts.append(request.prompt)
        prompt = request.prompt
        if "TASK 1 - complaints" in prompt:
            text = self.combined if isinstance(self.combined, str) else json.dumps(self.combined)
        elif "identify the complaints" in prompt:
            text = json.dumps(SEPARATE_COMPLAINTS)
        elif "overall sentiment" in prompt:
            text = json.dumps(SEPARATE_SENTIMENT)
        else:  # the escalation detector on its own
            text = json.dumps({"signals": []})
        return LLMResponse(text=text)


def _conversation() -> Conversation:
    call = Conversation(call_id="call-1")
    for i, (role, text) in enumerate(
        [
            (SpeakerRole.ICR, "Good morning, how can I help you?"),
            (SpeakerRole.CUSTOMER, "The bill was 14,000 but you quoted 8,000. The advisor was rude."),
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


def _providers(llm):
    return LLMComplaintProvider(llm), LLMSentimentProvider(llm), LLMEscalationProvider(llm)


def _analyzer(llm):
    complaints, sentiment, escalation = _providers(llm)
    return LLMLiveAnalysisProvider(llm, complaints, sentiment, escalation)


# ---- The combined request ----


def test_one_request_answers_all_three_with_each_tasks_own_rules():
    llm = ScriptedLLM(COMBINED)

    result = _analyzer(llm).analyze(_conversation())

    assert len(llm.prompts) == 1
    prompt = llm.prompts[0]
    assert prompt.count(MANAGER_LINE) == 1  # the transcript is sent once
    # Each task keeps its separate request's rules word for word.
    assert "Report each category at most once, even if it is raised repeatedly." in prompt
    assert "Determine the customer's overall sentiment across the whole conversation." in prompt
    assert "Use critical only for threats of legal action, a consumer court or the police." in prompt
    assert [c.category for c in result.complaints] == ["Cost", "Staff Behaviour"]
    assert result.sentiment.label is SentimentLabel.NEGATIVE
    assert [s.signal_type for s in result.escalation_signals] == [
        EscalationSignalType.MANAGER_REQUEST
    ]


def test_an_unusable_section_is_none_and_the_rest_are_kept():
    llm = ScriptedLLM({**COMBINED, "sentiment": {"label": "<POSITIVE | NEUTRAL | NEGATIVE>"}})

    result = _analyzer(llm).analyze(_conversation())

    assert result.sentiment is None
    assert result.complaints is not None and result.escalation_signals is not None


@pytest.mark.parametrize("answer", ["not json", "[]", '"text"'])
def test_an_unusable_answer_leaves_every_section_to_be_asked_separately(answer):
    result = _analyzer(ScriptedLLM(answer)).analyze(_conversation())

    assert (result.complaints, result.sentiment, result.escalation_signals) == (None, None, None)


def test_escalation_quotes_must_have_been_said_on_the_call():
    invented = json.loads(json.dumps(COMBINED))
    invented["escalation"]["signals"][0]["evidence"] = "I will call my lawyer"

    result = _analyzer(ScriptedLLM(invented)).analyze(_conversation())

    assert result.escalation_signals == ()


def test_without_an_llm_escalation_detector_there_is_no_escalation_task():
    llm = ScriptedLLM({key: COMBINED[key] for key in ("complaints", "sentiment")})
    complaints, sentiment, _ = _providers(llm)

    result = LLMLiveAnalysisProvider(llm, complaints, sentiment).analyze(_conversation())

    assert "TASK 3" not in llm.prompts[0]
    assert result.escalation_signals is None


# ---- Live analysis uses it; the final analysis does not ----


def _service(llm):
    complaints, sentiment, escalation = _providers(llm)
    return ConversationAnalysisService(
        ComplaintAnalysisService(complaints),
        SentimentAnalysisService(sentiment),
        live_analyzer=LLMLiveAnalysisProvider(llm, complaints, sentiment, escalation),
    )


def test_live_analysis_makes_one_request():
    llm = ScriptedLLM(COMBINED)

    result = _service(llm).analyze(_conversation(), ConversationCoverage("call-1"), live=True)

    assert len(llm.prompts) == 1
    assert {c.category for c in result.coverage.complaints} == {"Cost", "Staff Behaviour"}
    assert result.sentiment.label is SentimentLabel.NEGATIVE
    assert result.escalation_signals is not None


def test_a_missing_section_is_asked_for_on_its_own():
    llm = ScriptedLLM({**COMBINED, "complaints": "nothing"})

    result = _service(llm).analyze(_conversation(), ConversationCoverage("call-1"), live=True)

    assert len(llm.prompts) == 2  # combined, then complaints alone
    assert {c.category for c in result.coverage.complaints} == {"Cost"}
    assert result.sentiment.label is SentimentLabel.NEGATIVE  # from the combined answer


def test_the_final_analysis_uses_separate_requests():
    llm = ScriptedLLM(COMBINED)

    result = _service(llm).analyze(_conversation(), ConversationCoverage("call-1"))

    assert len(llm.prompts) == 2
    assert not any("TASK 1" in prompt for prompt in llm.prompts)
    assert result.escalation_signals is None


def test_escalation_uses_the_combined_signals_without_asking_again():
    llm = ScriptedLLM(COMBINED)
    service = EscalationService(
        InMemoryEscalationRepository(),
        HybridEscalationProvider(RuleBasedEscalationProvider(), LLMEscalationProvider(llm)),
    )
    signals = _analyzer(llm).analyze(_conversation()).escalation_signals
    requests = len(llm.prompts)

    escalation = service.assess(
        _conversation(), ConversationCoverage("call-1"), None, llm_signals=signals
    )

    assert len(llm.prompts) == requests
    assert EscalationSignalType.MANAGER_REQUEST in {s.signal_type for s in escalation.signals}


# ---- The setting ----


def test_the_mode_setting_turns_the_combined_request_on():
    llm = ScriptedLLM(COMBINED)
    complaints, sentiment, escalation = _providers(llm)
    hybrid = HybridEscalationProvider(RuleBasedEscalationProvider(), escalation)

    def build(mode):
        settings = Settings(_env_file=None, live_analysis_mode=mode)  # type: ignore[call-arg]
        return _build_live_analyzer(settings, complaints, sentiment, hybrid)

    assert build("separate") is None
    assert build("unknown") is None
    assert isinstance(build("combined"), LLMLiveAnalysisProvider)
