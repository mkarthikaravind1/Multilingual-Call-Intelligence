"""The tone of each customer line: the two extra labels, what the model is
asked and how its answer is read (good, partial and bad), where the tones
are stored, and that a line whose words changed is rated again."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.ai.complaint.llm_provider import LLMComplaintProvider
from app.ai.escalation.provider import EscalationContext
from app.ai.escalation.rule_based_provider import RuleBasedEscalationProvider
from app.ai.live_analysis.llm_provider import LLMLiveAnalysisProvider
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.sentiment.llm_provider import (
    MAX_LINES_PER_REQUEST,
    LLMSentimentProvider,
    lines_to_rate,
)
from app.ai.sentiment.provider import SentimentLabel, SentimentResult, UtteranceSentiment
from app.api.v1.mappers import to_call_response
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.escalation import EscalationSignalType
from app.domain.utterance import SpeakerRole, Utterance
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import build_session_factory
from app.infrastructure.database.repositories.conversation_repository import (
    PostgresConversationRepository,
)
from app.services.call_service import CallService
from app.services.call_workflow_service import rate_lines
from app.services.conversation_service import ConversationService
from app.services.in_memory_conversation_repository import InMemoryConversationRepository

LINES = [
    (SpeakerRole.ICR, "Good morning, how can I help you?"),
    (SpeakerRole.CUSTOMER, "My car was due yesterday and nobody called me."),
    (SpeakerRole.ICR, "I am sorry about that, let me check."),
    (SpeakerRole.CUSTOMER, "I have asked three times already. This is the last time."),
    (SpeakerRole.UNKNOWN, "Get me your manager or I go to consumer court."),
]


def _utterance(index: int, role: SpeakerRole, text: str, **fields) -> Utterance:
    return Utterance(
        utterance_id=f"u{index}",
        transcript=text,
        speaker_role=role,
        languages=("en",),
        start_time=float(index),
        end_time=index + 0.5,
        **fields,
    )


def _conversation(lines=LINES) -> Conversation:
    call = Conversation(call_id="call-1")
    for index, (role, text) in enumerate(lines, start=1):
        call.add_utterance(_utterance(index, role, text))
    return call


class _LLM(LLMClient):
    def __init__(self, answer) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.prompts.append(request.prompt)
        answer = self.answer
        return LLMResponse(text=answer if isinstance(answer, str) else json.dumps(answer))


def _overall(**extra) -> dict:
    return {"label": "FRUSTRATED", "confidence": 0.8, "evidence": "Asked three times.", **extra}


# ---- Labels ----

def test_frustrated_and_escalating_are_negative_tones():
    assert [label.value for label in SentimentLabel] == [
        "POSITIVE",
        "NEUTRAL",
        "NEGATIVE",
        "FRUSTRATED",
        "ESCALATING",
    ]
    assert [label for label in SentimentLabel if label.is_negative] == [
        SentimentLabel.NEGATIVE,
        SentimentLabel.FRUSTRATED,
        SentimentLabel.ESCALATING,
    ]


@pytest.mark.parametrize(
    ("label", "confidence", "flagged"),
    [
        (SentimentLabel.NEGATIVE, 0.9, True),
        (SentimentLabel.FRUSTRATED, 0.9, True),
        (SentimentLabel.ESCALATING, 0.8, True),
        (SentimentLabel.ESCALATING, 0.5, False),
        (SentimentLabel.NEUTRAL, 0.9, False),
        (SentimentLabel.POSITIVE, 0.9, False),
    ],
)
def test_a_clearly_negative_tone_of_any_kind_puts_the_call_on_watch(label, confidence, flagged):
    call = _conversation([(SpeakerRole.CUSTOMER, "Fine.")])
    context = EscalationContext(
        call, ConversationCoverage(call_id=call.call_id), SentimentResult(label, confidence, "Said so.")
    )

    signals = [
        s
        for s in RuleBasedEscalationProvider().assess(context).signals
        if s.signal_type is EscalationSignalType.NEGATIVE_TONE
    ]

    assert bool(signals) is flagged
    if flagged:
        assert label.value.lower() in signals[0].description


# ---- What is asked ----

def test_only_the_customers_unrated_lines_are_to_be_rated():
    call = _conversation()
    # ICR lines are never rated; a line of unknown speaker is (it may be the customer).
    assert list(lines_to_rate(call)) == [2, 4, 5]

    call.rate_utterances([UtteranceSentiment("u2", SentimentLabel.NEGATIVE, 0.7, LINES[1][1])])
    assert list(lines_to_rate(call)) == [4, 5]


def test_a_long_backlog_keeps_its_most_recent_lines():
    call = _conversation([(SpeakerRole.CUSTOMER, f"Line {n}.") for n in range(1, 61)])

    numbers = list(lines_to_rate(call))

    assert len(numbers) == MAX_LINES_PER_REQUEST
    assert numbers[0] == 21 and numbers[-1] == 60


def test_the_request_numbers_the_lines_and_sends_each_once():
    llm = _LLM(_overall())

    LLMSentimentProvider(llm).analyze(_conversation())

    prompt = llm.prompts[0]
    assert "[2] CUSTOMER: My car was due yesterday and nobody called me." in prompt
    assert "[3] ICR: I am sorry about that, let me check." in prompt
    assert "numbered lines of the conversation: 2, 4, 5." in prompt
    assert prompt.count("nobody called me") == 1
    assert '"lines": [{"line": <line number>' in prompt
    assert "FRUSTRATED or ESCALATING" in prompt


def test_with_nothing_to_rate_the_request_is_as_before():
    call = _conversation([(SpeakerRole.ICR, "Good morning."), (SpeakerRole.CUSTOMER, "Hello.")])
    call.rate_utterances([UtteranceSentiment("u2", SentimentLabel.NEUTRAL, 0.9, "Hello.")])
    llm = _LLM(_overall())

    result = LLMSentimentProvider(llm).analyze(call)

    prompt = llm.prompts[0]
    assert "ICR: Good morning.\nCUSTOMER: Hello." in prompt
    assert "[1]" not in prompt and '"lines"' not in prompt and "numbered lines" not in prompt
    assert result.lines == ()


# ---- How the answer is read ----

def test_line_tones_come_back_with_the_overall_tone():
    answer = _overall(
        lines=[
            {"line": 2, "label": "NEGATIVE", "confidence": 0.7},
            {"line": 4, "label": "frustrated", "confidence": 0.85},
            {"line": "5", "label": "ESCALATING", "confidence": 0.95},
        ]
    )

    result = LLMSentimentProvider(_LLM(answer)).analyze(_conversation())

    assert (result.label, result.confidence) == (SentimentLabel.FRUSTRATED, 0.8)
    assert [(l.utterance_id, l.label, l.confidence) for l in result.lines] == [
        ("u2", SentimentLabel.NEGATIVE, 0.7),
        ("u4", SentimentLabel.FRUSTRATED, 0.85),
        ("u5", SentimentLabel.ESCALATING, 0.95),
    ]
    assert result.lines[0].transcript == LINES[1][1]


@pytest.mark.parametrize(
    "lines",
    [
        None,
        "none",
        [],
        [{"line": 2}],
        [{"line": 2, "label": "ANGRY", "confidence": 0.9}],
        [{"line": 2, "label": "NEGATIVE", "confidence": 7}],
        [{"line": 2, "label": "NEGATIVE", "confidence": "high"}],
        [{"line": 3, "label": "NEGATIVE", "confidence": 0.9}],  # an ICR line
        [{"line": 99, "label": "NEGATIVE", "confidence": 0.9}],
        ["2: NEGATIVE"],
    ],
)
def test_bad_or_missing_line_tones_never_spoil_the_overall_tone(lines):
    answer = _overall() if lines is None else _overall(lines=lines)

    result = LLMSentimentProvider(_LLM(answer)).analyze(_conversation())

    assert result.label is SentimentLabel.FRUSTRATED
    assert result.lines == ()


def test_usable_line_tones_are_kept_when_others_are_not():
    answer = _overall(
        lines=[
            {"line": 2, "label": "ANGRY", "confidence": 0.9},
            {"line": 4, "label": "FRUSTRATED", "confidence": 0.8},
            {"line": 4, "label": "ESCALATING", "confidence": 0.6},  # the later one counts
        ]
    )

    result = LLMSentimentProvider(_LLM(answer)).analyze(_conversation())

    assert [(l.utterance_id, l.label) for l in result.lines] == [("u4", SentimentLabel.ESCALATING)]


def test_an_unusable_answer_is_neutral_with_no_line_tones():
    result = LLMSentimentProvider(_LLM("not json")).analyze(_conversation())

    assert (result.label, result.confidence, result.lines) == (SentimentLabel.NEUTRAL, 0.0, ())


def test_the_combined_live_request_rates_lines_in_the_same_request():
    llm = _LLM(
        {
            "complaints": [],
            "sentiment": _overall(lines=[{"line": 5, "label": "ESCALATING", "confidence": 0.9}]),
        }
    )
    analyzer = LLMLiveAnalysisProvider(llm, LLMComplaintProvider(llm), LLMSentimentProvider(llm))

    result = analyzer.analyze(_conversation())

    assert len(llm.prompts) == 1
    prompt = llm.prompts[0]
    assert "[5] UNKNOWN: Get me your manager or I go to consumer court." in prompt
    assert prompt.count("consumer court") == 1
    assert "numbered lines of the conversation: 2, 4, 5." in prompt
    assert [(l.utterance_id, l.label) for l in result.sentiment.lines] == [
        ("u5", SentimentLabel.ESCALATING)
    ]


# ---- Where the tones are kept ----

def _call_service(repository=None) -> CallService:
    service = CallService(ConversationService(repository or InMemoryConversationRepository()))
    service.start_call("call-1", 0.0)
    for index, (role, text) in enumerate(LINES, start=1):
        service.add_utterance("call-1", _utterance(index, role, text))
    return service


def _tones(service: CallService) -> list:
    return [(u.sentiment, u.sentiment_confidence) for u in service.get_call("call-1").utterances]


def test_rated_lines_keep_their_tone_and_the_rest_stay_empty():
    service = _call_service()

    rate_lines(
        service,
        "call-1",
        SentimentResult(
            SentimentLabel.FRUSTRATED,
            0.8,
            "Asked three times.",
            (
                UtteranceSentiment("u2", SentimentLabel.NEGATIVE, 0.7, LINES[1][1]),
                UtteranceSentiment("u4", SentimentLabel.FRUSTRATED, 0.85, LINES[3][1]),
                UtteranceSentiment("gone", SentimentLabel.POSITIVE, 0.9, "No such line."),
            ),
        ),
    )

    assert _tones(service) == [
        (None, None),
        (SentimentLabel.NEGATIVE, 0.7),
        (None, None),
        (SentimentLabel.FRUSTRATED, 0.85),
        (None, None),
    ]
    assert list(lines_to_rate(service.get_call("call-1"))) == [5]


def test_a_line_whose_words_changed_since_it_was_rated_is_rated_again():
    service = _call_service()
    rating = UtteranceSentiment("u5", SentimentLabel.NEGATIVE, 0.6, LINES[4][1])
    # Live speech continued the last line while the analysis was running.
    service.update_latest_utterance(
        "call-1", _utterance(5, SpeakerRole.UNKNOWN, LINES[4][1] + " I mean it.")
    )

    service.rate_utterances("call-1", [rating])

    assert _tones(service)[4] == (None, None)
    assert 5 in lines_to_rate(service.get_call("call-1"))


def test_a_continued_line_loses_its_old_tone():
    service = _call_service()
    service.rate_utterances(
        "call-1", [UtteranceSentiment("u5", SentimentLabel.NEGATIVE, 0.6, LINES[4][1])]
    )

    service.update_latest_utterance(
        "call-1", _utterance(5, SpeakerRole.UNKNOWN, LINES[4][1] + " I mean it.")
    )

    assert _tones(service)[4] == (None, None)


def test_lines_of_a_completed_call_can_still_be_rated():
    service = _call_service()
    service.end_call("call-1", 60.0)

    service.rate_utterances(
        "call-1", [UtteranceSentiment("u2", SentimentLabel.NEGATIVE, 0.7, LINES[1][1])]
    )

    assert _tones(service)[1] == (SentimentLabel.NEGATIVE, 0.7)


def test_results_without_line_tones_and_storage_failures_are_harmless():
    class _Broken:
        def annotate_utterances(self, call_id, ratings, categories):
            raise RuntimeError("database is down")

    rate_lines(_Broken(), "call-1", SentimentResult(SentimentLabel.NEUTRAL, 0.5, "Calm."))
    rate_lines(_Broken(), "call-1", None)
    # Storing fails: logged, not raised.
    rate_lines(
        _Broken(),
        "call-1",
        SentimentResult(
            SentimentLabel.NEUTRAL,
            0.5,
            "Calm.",
            (UtteranceSentiment("u2", SentimentLabel.NEUTRAL, 0.5, "x"),),
        ),
    )


def test_line_tones_are_stored_in_the_database_and_shown_by_the_api():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    try:
        service = _call_service(PostgresConversationRepository(build_session_factory(engine)))
        service.rate_utterances(
            "call-1", [UtteranceSentiment("u4", SentimentLabel.ESCALATING, 0.9, LINES[3][1])]
        )

        assert _tones(service)[3] == (SentimentLabel.ESCALATING, 0.9)
        assert _tones(service)[0] == (None, None)
        body = to_call_response(service.get_call("call-1")).model_dump(mode="json")
        assert (body["utterances"][3]["sentiment"], body["utterances"][3]["sentiment_confidence"]) == (
            "ESCALATING",
            0.9,
        )
        assert body["utterances"][0]["sentiment"] is None
    finally:
        engine.dispose()


def test_a_line_tone_must_be_a_known_label_with_a_sane_confidence():
    with pytest.raises(TypeError):
        UtteranceSentiment("u1", "NEGATIVE", 0.5, "x")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        UtteranceSentiment("u1", SentimentLabel.NEGATIVE, 1.5, "x")
    with pytest.raises(ValueError):
        _utterance(1, SpeakerRole.CUSTOMER, "x", sentiment_confidence=2.0)
