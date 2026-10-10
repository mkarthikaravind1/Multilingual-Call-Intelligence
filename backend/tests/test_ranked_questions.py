"""Suggested questions as a ranked list: several in one request, one check
for all of them, written by the combined live request when there is one
(shown at once, checked a moment later), never repeating a question the
executive has already accepted or skipped."""

import json

import pytest

from app.ai.complaint.llm_provider import LLMComplaintProvider
from app.ai.escalation.llm_provider import LLMEscalationProvider
from app.ai.live_analysis.llm_provider import LLMLiveAnalysisProvider
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.question.llm_provider import LLMQuestionProvider
from app.ai.question.provider import OpenComplaint, QuestionGenerationContext
from app.ai.question.rule_based_provider import RuleBasedQuestionProvider
from app.ai.sentiment.llm_provider import LLMSentimentProvider
from app.ai.summary.rule_based_provider import RuleBasedSummaryProvider
from app.api.v1.mappers import to_analysis_response
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource
from app.domain.utterance import SpeakerRole, Utterance
from app.estimation.default_pricing import DEFAULT_PRICING_CONFIG
from app.estimation.rule_based_provider import RuleBasedEstimationProvider
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.conversation_analysis_service import ConversationAnalysisService
from app.services.conversation_service import ConversationService
from app.services.estimation_service import EstimationService
from app.services.in_memory_conversation_coverage_repository import (
    InMemoryConversationCoverageRepository,
)
from app.services.in_memory_conversation_repository import InMemoryConversationRepository
from app.services.live_analysis_store import (
    LiveAnalysisSnapshot,
    LiveAnalysisStore,
    _deserialize,
    _serialize,
)
from app.services.live_state_store import InMemoryLiveStateStore
from app.services.next_question_service import NextQuestionService
from app.services.post_call_summary_service import PostCallSummaryService
from app.services.sentiment_analysis_service import SentimentAnalysisService

CALL_ID = "call-1"
DETECTED = ComplaintCoverageStatus.DETECTED
PROBED = ComplaintCoverageStatus.PROBED

Q_BILL = {
    "question": "What amount were you quoted before the work started?",
    "target_category": "Cost",
    "reason": "The quoted amount is not known.",
}
Q_DIRT = {
    "question": "Which part of the car was left dirty?",
    "target_category": "Hygiene",
    "reason": "Where the dirt was is not known.",
}
Q_DATE = {
    "question": "Which date were you promised the car?",
    "target_category": "Turnaround Time",
    "reason": "The promised date is not known.",
}


def _utterances(*lines: tuple[SpeakerRole, str]) -> tuple[Utterance, ...]:
    return tuple(
        Utterance(f"u{i}", text, role, ("en",), float(i), i + 0.5)
        for i, (role, text) in enumerate(lines, start=1)
    )


SPOKEN = _utterances(
    (SpeakerRole.ICR, "Good morning, how can I help you?"),
    (SpeakerRole.CUSTOMER, "The bill was far too high and the car came back dirty."),
)


def _context(*categories: str, **fields) -> QuestionGenerationContext:
    categories = categories or ("Cost", "Hygiene")
    return QuestionGenerationContext(
        category=categories[0],
        status=DETECTED,
        utterances=SPOKEN,
        open_complaints=tuple(OpenComplaint(c, DETECTED) for c in categories),
        **fields,
    )


def _coverage(**complaints: ComplaintCoverageStatus) -> ConversationCoverage:
    coverage = ConversationCoverage(CALL_ID)
    for category, status in complaints.items():
        coverage.add(category.replace("_", " ")).status = status
    return coverage


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


def _provider(*answers, check=None, **options) -> tuple[LLMQuestionProvider, AnswersInTurn]:
    llm = AnswersInTurn(*answers)
    return (
        LLMQuestionProvider(
            llm,
            fallback=RuleBasedQuestionProvider(),
            check_answered=check is not None,
            check_client=check,
            **options,
        ),
        llm,
    )


def _texts(suggestions) -> list[str]:
    return [s.question for s in suggestions]


# ---- Several questions in one request ----


def test_one_request_asks_for_up_to_the_limit_most_useful_first():
    provider, llm = _provider([Q_BILL, Q_DIRT])

    suggestions = provider.generate_ranked(_context(), 3)

    (prompt,) = llm.prompts
    assert "Suggest up to 3 questions, the most useful first" in prompt
    assert "- Cost (detected): the amount quoted and the amount billed" in prompt
    assert "- Hygiene (detected): what was left dirty" in prompt
    assert "CUSTOMER: The bill was far too high and the car came back dirty." in prompt
    assert "ONLY a JSON array of at most 3 items" in prompt
    assert "respond with exactly: []" in prompt
    # Nothing missing about a complaint means no question about it, not no answer.
    assert "respond with null" not in prompt
    assert "Suggest no question about a complaint when nothing about it is still missing." in prompt
    # The place in the list is the priority.
    assert [(s.question, s.target_category, s.priority) for s in suggestions] == [
        (Q_BILL["question"], "Cost", 0),
        (Q_DIRT["question"], "Hygiene", 1),
    ]
    assert all(s.source is SuggestionSource.LLM for s in suggestions)


def test_no_missing_fact_is_no_question_and_no_fallback():
    provider, llm = _provider([])

    assert provider.generate_ranked(_context(), 3) == ()
    assert len(llm.prompts) == 1


def test_an_unusable_question_is_left_out_and_the_rest_kept():
    answer = [
        {"question": "No category?", "reason": "x"},
        Q_BILL,
        "what was dirty?",
        {**Q_DATE},  # Turnaround Time is not an open complaint of this call
        Q_DIRT,
        {**Q_BILL},  # the same question again
    ]
    provider, _ = _provider(answer)

    suggestions = provider.generate_ranked(_context(), 3)

    assert _texts(suggestions) == [Q_BILL["question"], Q_DIRT["question"]]
    assert [s.priority for s in suggestions] == [0, 1]


def test_more_questions_than_the_limit_are_cut():
    provider, _ = _provider([Q_BILL, Q_DIRT, Q_DATE])

    suggestions = provider.generate_ranked(_context("Cost", "Hygiene", "Turnaround Time"), 2)

    assert _texts(suggestions) == [Q_BILL["question"], Q_DIRT["question"]]


@pytest.mark.parametrize(
    "answer", ["not json", {"question": "one object"}, [{"question": "", "reason": ""}], RuntimeError("down")]
)
def test_an_unusable_answer_falls_back_to_one_fixed_question_per_open_complaint(answer):
    provider, _ = _provider(answer)

    suggestions = provider.generate_ranked(_context(), 3)

    assert [(s.target_category, s.source) for s in suggestions] == [
        ("Cost", SuggestionSource.RULE_BASED),
        ("Hygiene", SuggestionSource.RULE_BASED),
    ]


def test_the_fixed_questions_follow_each_complaints_own_status_up_to_the_limit():
    context = QuestionGenerationContext(
        category="Cost",
        status=DETECTED,
        utterances=SPOKEN,
        open_complaints=(
            OpenComplaint("Cost", PROBED),
            OpenComplaint("Hygiene", DETECTED),
            OpenComplaint("Communication", DETECTED),
        ),
    )

    suggestions = RuleBasedQuestionProvider().generate_ranked(context, 2)

    assert [s.target_category for s in suggestions] == ["Cost", "Hygiene"]
    assert suggestions[0].question == "Was the amount charged different from what was originally quoted?"
    assert suggestions[1].question == "Could you describe the hygiene issue you noticed?"


def test_questions_already_accepted_or_skipped_are_not_suggested_again():
    provider, llm = _provider([Q_BILL, Q_DIRT])

    suggestions = provider.generate_ranked(
        _context(handled_questions=(Q_BILL["question"],)), 3
    )

    assert "Do not suggest these questions again" in llm.prompts[0]
    assert Q_BILL["question"] in llm.prompts[0]
    # Left out even when the model suggests it anyway.
    assert _texts(suggestions) == [Q_DIRT["question"]]


TAMIL_QUESTION = "வேலை தொடங்கும் முன் எவ்வளவு தொகை சொன்னார்கள்?"


def test_questions_for_another_language_carry_an_english_line_each():
    answer = [
        {**Q_BILL, "question": TAMIL_QUESTION, "question_en": Q_BILL["question"]},
        # Not in Tamil script: unusable.
        {**Q_DIRT, "question_en": Q_DIRT["question"]},
    ]
    provider, llm = _provider(answer)

    suggestions = provider.generate_ranked(_context(language="ta"), 3)

    assert '"question_en": "<the same question in English>"' in llm.prompts[0]
    assert [(s.question, s.question_en, s.language) for s in suggestions] == [
        (TAMIL_QUESTION, Q_BILL["question"], "ta")
    ]


# ---- One check for all of them ----


def test_one_check_request_covers_every_question_and_drops_the_answered_ones():
    check = AnswersInTurn({"answered": [1]})
    provider, llm = _provider([Q_BILL, Q_DIRT, Q_DATE], check=check)

    suggestions = provider.generate_ranked(_context("Cost", "Hygiene", "Turnaround Time"), 3)

    assert len(llm.prompts) == 1  # written once, with no second try
    (prompt,) = check.prompts
    assert f"1. {Q_BILL['question']}" in prompt and f"3. {Q_DATE['question']}" in prompt
    # The places close up.
    assert [(s.question, s.priority) for s in suggestions] == [
        (Q_DIRT["question"], 0),
        (Q_DATE["question"], 1),
    ]


@pytest.mark.parametrize("answer", ["not json", {"answered": "none"}, {}, RuntimeError("down")])
def test_a_failed_check_keeps_every_question(answer):
    provider, _ = _provider([Q_BILL, Q_DIRT], check=AnswersInTurn(answer))

    assert len(provider.generate_ranked(_context(), 3)) == 2


def test_nothing_to_check_makes_no_request():
    check = AnswersInTurn()
    provider, _ = _provider([], check=check)

    provider.generate_ranked(_context(), 3)

    assert check.prompts == []


# ---- The service ----


def test_a_call_with_no_open_complaint_gets_no_question_and_no_request():
    provider, llm = _provider()
    service = NextQuestionService(provider)

    assert service.suggest_questions(_coverage(Cost=ComplaintCoverageStatus.RESOLVED), SPOKEN) == ()
    assert llm.prompts == []


def test_the_service_asks_for_its_limit_of_questions():
    provider, llm = _provider([Q_BILL, Q_DIRT])
    service = NextQuestionService(provider, limit=2)

    suggestions = service.suggest_questions(_coverage(Cost=DETECTED, Hygiene=PROBED), SPOKEN)

    assert "Suggest up to 2 questions" in llm.prompts[0]
    assert "- Hygiene (probed)" in llm.prompts[0]
    assert len(suggestions) == 2


def test_only_a_provider_that_can_takes_part_in_a_combined_request():
    llm_provider, _ = _provider()

    assert NextQuestionService(RuleBasedQuestionProvider()).live_task(SPOKEN) is None
    assert NextQuestionService(llm_provider, in_live_analysis=False).live_task(SPOKEN) is None
    task = NextQuestionService(llm_provider).live_task(SPOKEN, ("Asked already?",))
    assert '"questions" is a JSON array of at most 3 items' in task
    assert "<a complaint category you report in TASK 1>" in task
    assert "- Cost: the amount quoted and the amount billed" in task
    assert "Asked already?" in task
    # The conversation is in the combined request already.
    assert "The bill was far too high" not in task


def test_drafted_questions_are_held_against_the_complaints_the_analysis_left_open():
    provider, _ = _provider()
    service = NextQuestionService(provider)
    coverage = _coverage(Cost=DETECTED, Hygiene=ComplaintCoverageStatus.COVERED)

    drafted = service.drafted_questions(coverage, SPOKEN, [Q_BILL, Q_DIRT])

    # Hygiene has been dealt with: no question about it.
    assert _texts(drafted) == [Q_BILL["question"]]
    assert service.drafted_questions(coverage, SPOKEN, "none") is None
    assert service.drafted_questions(coverage, SPOKEN, None) is None
    assert service.drafted_questions(_coverage(), SPOKEN, [Q_BILL]) == ()
    assert service.drafted_questions(coverage, SPOKEN, []) == ()
    assert NextQuestionService(RuleBasedQuestionProvider()).drafted_questions(
        coverage, SPOKEN, [Q_BILL]
    ) is None


# ---- Written by the combined live request ----

COMPLAINTS = [
    {"category": "Cost", "confidence": 0.9, "evidence": "The bill was too high.", "lines": [2]},
    {"category": "Hygiene", "confidence": 0.8, "evidence": "The car was dirty.", "lines": [2]},
]
SENTIMENT = {"label": "NEGATIVE", "confidence": 0.9, "evidence": "Unhappy."}
COMBINED = {
    "complaints": COMPLAINTS,
    "sentiment": SENTIMENT,
    "escalation": {"signals": []},
    "questions": [Q_BILL, Q_DIRT],
}


class _Call:
    """A live call whose AI is one scripted client, with the stored live
    analysis open to inspection."""

    def __init__(self, *answers, check=None, handled=()) -> None:
        self.llm = AnswersInTurn(*answers)
        self.check = check
        complaints = LLMComplaintProvider(self.llm)
        sentiment = LLMSentimentProvider(self.llm)
        questions = LLMQuestionProvider(
            self.llm,
            fallback=RuleBasedQuestionProvider(),
            check_answered=check is not None,
            check_client=check,
        )
        self.state = InMemoryLiveStateStore()
        self.stored = LiveAnalysisStore(self.state)
        self.call_service = CallService(ConversationService(InMemoryConversationRepository()))
        self.call_service.start_call(CALL_ID)
        for utterance in SPOKEN:
            self.call_service.add_utterance(CALL_ID, utterance)
        self.workflow = CallWorkflowService(
            self.call_service,
            InMemoryConversationCoverageRepository(),
            ConversationAnalysisService(
                ComplaintAnalysisService(complaints),
                SentimentAnalysisService(sentiment),
                live_analyzer=LLMLiveAnalysisProvider(
                    self.llm, complaints, sentiment, LLMEscalationProvider(self.llm)
                ),
            ),
            NextQuestionService(questions),
            EstimationService(RuleBasedEstimationProvider(DEFAULT_PRICING_CONFIG)),
            PostCallSummaryService(RuleBasedSummaryProvider()),
            live_state_store=self.state,
            handled_questions=lambda call_id: tuple(handled),
        )

    def analyze(self):
        return self.workflow.analyze_latest_speech(CALL_ID)


def test_the_combined_request_writes_the_questions_with_no_request_of_their_own():
    call = _Call(COMBINED)

    result = call.analyze()

    (prompt,) = call.llm.prompts
    assert "TASK 4 - questions." in prompt
    assert '"complaints", "sentiment", "escalation", "questions"' in prompt
    assert prompt.count("The bill was far too high") == 1  # the transcript is sent once
    assert _texts(result.question_suggestions) == [Q_BILL["question"], Q_DIRT["question"]]
    assert result.question_suggestion == result.question_suggestions[0]
    assert {c.category for c in result.coverage.complaints} == {"Cost", "Hygiene"}


def test_the_questions_show_at_once_and_the_check_takes_out_the_answered_ones():
    seen_while_checking = []

    class _Check(LLMClient):
        def complete(self, request):
            # What the executive's screen shows while the check runs.
            seen_while_checking.append(_texts(call.stored.load(CALL_ID).question_suggestions))
            return LLMResponse(text=json.dumps({"answered": [1]}))

    call = _Call(COMBINED, check=_Check())

    result = call.analyze()

    assert seen_while_checking == [[Q_BILL["question"], Q_DIRT["question"]]]
    assert _texts(result.question_suggestions) == [Q_DIRT["question"]]
    assert _texts(call.stored.load(CALL_ID).question_suggestions) == [Q_DIRT["question"]]
    assert len(call.llm.prompts) == 1


def test_a_combined_answer_without_questions_has_them_asked_for_on_their_own():
    call = _Call({key: COMBINED[key] for key in ("complaints", "sentiment", "escalation")}, [Q_DIRT])

    result = call.analyze()

    assert len(call.llm.prompts) == 2
    assert "TASK 1" not in call.llm.prompts[1]
    assert "Suggest up to 3 questions" in call.llm.prompts[1]
    assert _texts(result.question_suggestions) == [Q_DIRT["question"]]


def test_no_fact_missing_in_the_combined_answer_is_no_question_and_no_extra_request():
    call = _Call({**COMBINED, "questions": []})

    result = call.analyze()

    assert len(call.llm.prompts) == 1
    assert (result.question_suggestions, result.question_suggestion) == ((), None)


def test_a_handled_question_is_ruled_out_in_the_combined_request_too():
    call = _Call(COMBINED, handled=(Q_BILL["question"],))

    result = call.analyze()

    assert "Do not suggest these questions again" in call.llm.prompts[0]
    assert _texts(result.question_suggestions) == [Q_DIRT["question"]]


def test_reading_the_call_shows_the_list_without_asking_again():
    call = _Call(COMBINED)
    call.analyze()

    read = call.workflow.analyze_call(CALL_ID)

    assert _texts(read.question_suggestions) == [Q_BILL["question"], Q_DIRT["question"]]
    assert len(call.llm.prompts) == 1
    shown = to_analysis_response(CALL_ID, read).model_dump()
    assert [q["question"] for q in shown["question_suggestions"]] == _texts(
        read.question_suggestions
    )
    assert shown["question_suggestion"]["question"] == Q_BILL["question"]


# ---- Stored and shown ----


def _suggestion(text: str, rank: int = 0) -> QuestionSuggestion:
    return QuestionSuggestion(text, "Cost", rank, "Why.", SuggestionSource.LLM)


def test_the_stored_live_analysis_keeps_the_whole_list_in_order():
    snapshot = LiveAnalysisSnapshot(None, (_suggestion("First?"), _suggestion("Second?", 1)), None)

    restored = _deserialize(json.loads(json.dumps(_serialize(snapshot))))

    assert restored == snapshot
    assert restored.question_suggestion == _suggestion("First?")
    assert LiveAnalysisSnapshot(None, (), None).question_suggestion is None


def test_a_live_analysis_stored_before_the_list_still_reads():
    stored = _serialize(LiveAnalysisSnapshot(None, (_suggestion("Only?"),), None))
    del stored["question_suggestions"]

    assert _deserialize(stored).question_suggestions == (_suggestion("Only?"),)
    stored["question_suggestion"] = None
    assert _deserialize(stored).question_suggestions == ()
