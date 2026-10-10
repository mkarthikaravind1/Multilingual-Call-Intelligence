"""The complaint categories each line of a call raises: asked for inside the
complaint request that already exists, stored on the line with a flag when
it covers several issues, kept right as the call goes on, shown by the API,
and quoted in reports."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.ai.complaint.llm_provider import LLMComplaintProvider
from app.ai.complaint.provider import (
    ComplaintDetectionProvider,
    ComplaintDetectionResult,
    UtteranceCategories,
    line_categories,
)
from app.ai.escalation.llm_provider import LLMEscalationProvider
from app.ai.live_analysis.llm_provider import LLMLiveAnalysisProvider
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.question.rule_based_provider import RuleBasedQuestionProvider
from app.ai.sentiment.llm_provider import LLMSentimentProvider
from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
    UtteranceSentiment,
)
from app.ai.summary.rule_based_provider import RuleBasedSummaryProvider
from app.api.v1.mappers import to_call_response
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.post_call_summary import ComplaintSummary, PostCallSummary
from app.domain.utterance import SpeakerRole, Utterance
from app.estimation.default_pricing import DEFAULT_PRICING_CONFIG
from app.estimation.rule_based_provider import RuleBasedEstimationProvider
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import build_session_factory
from app.infrastructure.database.repositories.conversation_coverage_repository import (
    PostgresConversationCoverageRepository,
)
from app.infrastructure.database.repositories.conversation_repository import (
    PostgresConversationRepository,
)
from app.infrastructure.database.repositories.post_call_summary_repository import (
    PostgresPostCallSummaryRepository,
)
from app.infrastructure.database.repositories.report_source import PostgresReportSource
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
from app.services.next_question_service import NextQuestionService
from app.services.post_call_summary_repository import InMemoryPostCallSummaryRepository
from app.services.post_call_summary_service import PostCallSummaryService
from app.services.report_export import export_report
from app.services.reporting import (
    MAX_QUOTE_CHARS,
    InMemoryReportSource,
    ReportFilters,
    ReportService,
    first_quotes,
)
from app.services.sentiment_analysis_service import SentimentAnalysisService

CALL_ID = "call-1"
LINES = (
    (SpeakerRole.ICR, "Good morning, how can I help you?"),
    (SpeakerRole.CUSTOMER, "The bill was 14,000 but you quoted 8,000."),
    (SpeakerRole.CUSTOMER, "And the car came back dirty and two days late."),
    (SpeakerRole.ICR, "I am sorry to hear that."),
)


def _utterance(index: int, role: SpeakerRole, text: str) -> Utterance:
    return Utterance(f"u{index}", text, role, ("en",), float(index), index + 0.5)


def _conversation(lines=LINES) -> Conversation:
    call = Conversation(call_id=CALL_ID)
    for index, (role, text) in enumerate(lines, start=1):
        call.add_utterance(_utterance(index, role, text))
    return call


def _item(category: str, lines=None, **extra) -> dict:
    item = {"category": category, "confidence": 0.9, "evidence": "Said so.", **extra}
    if lines is not None:
        item["lines"] = lines
    return item


class _LLM(LLMClient):
    """Answers every request with the same text; records the prompts."""

    def __init__(self, answer) -> None:
        self.answer = answer if isinstance(answer, str) else json.dumps(answer)
        self.prompts: list[str] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.prompts.append(request.prompt)
        return LLMResponse(text=self.answer)


def _detect(answer) -> list[ComplaintDetectionResult]:
    return LLMComplaintProvider(_LLM(answer)).detect(_conversation())


def _tags(conversation: Conversation) -> list[tuple[str, ...]]:
    return [u.complaint_categories for u in conversation.utterances]


# ---- Asked for inside the complaint request ----


def test_the_complaint_request_numbers_the_lines_and_asks_which_raise_each_complaint():
    llm = _LLM([])

    LLMComplaintProvider(llm).detect(_conversation())

    (prompt,) = llm.prompts  # still one request
    assert "[2] CUSTOMER: The bill was 14,000 but you quoted 8,000." in prompt
    assert "[4] ICR: I am sorry to hear that." in prompt
    assert '"lines": [<line number>, ...]' in prompt
    assert "A line that covers several complaints is listed under each of them." in prompt
    # Each line is sent once.
    assert prompt.count("The bill was 14,000") == 1


def test_the_lines_come_back_with_each_complaint():
    results = _detect([_item("Cost", [2]), _item("Hygiene", [3]), _item("Turnaround Time", [3])])

    assert [(r.category, r.lines) for r in results] == [
        ("Cost", (2,)),
        ("Hygiene", (3,)),
        ("Turnaround Time", (3,)),
    ]


@pytest.mark.parametrize(
    ("lines", "kept"),
    [
        (None, ()),
        ("2", ()),
        ({"line": 2}, ()),
        ([], ()),
        ([2, "3", " 4 ", 2], (2, 3, 4)),
        ([0, -1, 2.5, True, None, "two", [2], 3], (3,)),
    ],
)
def test_bad_or_missing_line_numbers_never_spoil_the_complaint(lines, kept):
    (result,) = _detect([_item("Cost", lines)])

    assert (result.category, result.confidence, result.lines) == ("Cost", 0.9, kept)


def test_a_category_reported_twice_keeps_the_lines_of_both():
    (result,) = _detect([_item("Cost", [2]), _item("cost", [3, 2])])

    assert result.lines == (2, 3)


# ---- From detections to tags on lines ----


def _detection(category: str, *lines: int) -> ComplaintDetectionResult:
    return ComplaintDetectionResult(category, 0.9, "Said so.", lines=lines)


def test_every_line_gets_what_it_raises_and_the_rest_nothing():
    tags = line_categories(
        _conversation(),
        [_detection("Cost", 2), _detection("Hygiene", 3), _detection("Turnaround Time", 3)],
    )

    assert [(t.utterance_id, t.categories) for t in tags] == [
        ("u1", ()),
        ("u2", ("Cost",)),
        ("u3", ("Hygiene", "Turnaround Time")),
        ("u4", ()),
    ]
    assert tags[1].transcript == "The bill was 14,000 but you quoted 8,000."


def test_a_line_number_that_is_not_a_line_of_the_call_is_ignored():
    tags = line_categories(_conversation(), [_detection("Cost", 2, 9), _detection("Hygiene", 7)])

    assert [t.categories for t in tags] == [(), ("Cost",), (), ()]


@pytest.mark.parametrize(
    "detections",
    [
        [],
        [ComplaintDetectionResult("Cost", 0.9, "Said so.")],
        [_detection("Cost", 99)],
    ],
)
def test_detections_that_name_no_line_say_nothing_about_the_lines(detections):
    assert line_categories(_conversation(), detections) is None


# ---- Stored on the line ----


def _entry(utterance: Utterance, *categories: str) -> UtteranceCategories:
    return UtteranceCategories(utterance.utterance_id, categories, utterance.transcript)


def test_lines_keep_their_categories_and_say_when_they_cover_several():
    call = _conversation()
    one, two = call.utterances[1], call.utterances[2]

    changed = call.annotate_utterances(
        categories=[_entry(one, "Cost"), _entry(two, "Hygiene", "Turnaround Time")]
    )

    assert changed == 2
    assert _tags(call) == [(), ("Cost",), ("Hygiene", "Turnaround Time"), ()]
    assert [u.multi_category for u in call.utterances] == [False, False, True, False]
    # The same again changes nothing (so nothing is saved).
    assert call.annotate_utterances(categories=[_entry(one, "Cost")]) == 0


def test_a_line_whose_words_changed_since_it_was_analysed_is_not_tagged():
    call = _conversation()
    stale = UtteranceCategories("u2", ("Cost",), "The bill was")

    assert call.annotate_utterances(categories=[stale]) == 0
    assert _tags(call)[1] == ()


def test_a_line_no_longer_named_loses_its_categories():
    call = _conversation()
    call.annotate_utterances(categories=[_entry(call.utterances[1], "Cost")])

    call.annotate_utterances(categories=[_entry(call.utterances[1])])

    assert _tags(call)[1] == ()


def test_tones_and_categories_are_stored_together():
    call = _conversation()
    line = call.utterances[1]
    tone = UtteranceSentiment(line.utterance_id, SentimentLabel.FRUSTRATED, 0.8, line.transcript)

    assert call.annotate_utterances([tone], [_entry(line, "Cost")]) == 1

    stored = call.utterances[1]
    assert (stored.sentiment, stored.complaint_categories) == (SentimentLabel.FRUSTRATED, ("Cost",))
    # Rating a line again keeps what it raises.
    call.rate_utterances([tone])
    assert call.utterances[1].complaint_categories == ("Cost",)


class _CountingRepository(InMemoryConversationRepository):
    def __init__(self) -> None:
        super().__init__()
        self.saves = 0

    def save(self, conversation):
        self.saves += 1
        super().save(conversation)


def test_one_save_stores_both_and_none_when_nothing_changed():
    repository = _CountingRepository()
    service = CallService(ConversationService(repository))
    service.start_call(CALL_ID)
    for index, (role, text) in enumerate(LINES, start=1):
        service.add_utterance(CALL_ID, _utterance(index, role, text))
    line = service.get_call(CALL_ID).utterances[1]
    tone = UtteranceSentiment(line.utterance_id, SentimentLabel.NEGATIVE, 0.7, line.transcript)
    repository.saves = 0

    service.annotate_utterances(CALL_ID, [tone], [_entry(line, "Cost")])
    service.annotate_utterances(CALL_ID, [tone], [_entry(line, "Cost")])

    assert repository.saves == 1


# ---- Through a call: live, as it goes on, and after it ----


class _Detections(ComplaintDetectionProvider):
    def __init__(self) -> None:
        self.results: list[ComplaintDetectionResult] = []

    def detect(self, conversation, learning_context=()):
        return list(self.results)


class _Calm(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEUTRAL, 0.7, "Calm.")


def _workflow(complaints) -> tuple[CallWorkflowService, CallService]:
    call_service = CallService(ConversationService(InMemoryConversationRepository()))
    call_service.start_call(CALL_ID)
    workflow = CallWorkflowService(
        call_service,
        InMemoryConversationCoverageRepository(),
        ConversationAnalysisService(
            ComplaintAnalysisService(complaints), SentimentAnalysisService(_Calm())
        ),
        NextQuestionService(RuleBasedQuestionProvider()),
        EstimationService(RuleBasedEstimationProvider(DEFAULT_PRICING_CONFIG)),
        PostCallSummaryService(RuleBasedSummaryProvider()),
    )
    return workflow, call_service


def test_a_live_calls_lines_are_tagged_and_corrected_as_it_goes_on():
    complaints = _Detections()
    workflow, call_service = _workflow(complaints)
    call_service.add_utterance(CALL_ID, _utterance(1, *LINES[0]))
    call_service.add_utterance(CALL_ID, _utterance(2, *LINES[1]))

    complaints.results = [_detection("Cost", 2)]
    workflow.analyze_latest_speech(CALL_ID)
    assert _tags(call_service.get_call(CALL_ID)) == [(), ("Cost",)]

    # With more said, the detector places the complaints differently.
    call_service.add_utterance(CALL_ID, _utterance(3, *LINES[2]))
    complaints.results = [_detection("Cost", 2), _detection("Hygiene", 3), _detection("Cost", 3)]
    workflow.analyze_latest_speech(CALL_ID)
    call = call_service.get_call(CALL_ID)
    assert _tags(call) == [(), ("Cost",), ("Hygiene", "Cost")]
    assert call.utterances[2].multi_category

    # An answer that names no line (e.g. it could not be used) changes nothing.
    call_service.add_utterance(CALL_ID, _utterance(4, SpeakerRole.CUSTOMER, "Hello?"))
    complaints.results = []
    workflow.analyze_latest_speech(CALL_ID)
    assert _tags(call_service.get_call(CALL_ID))[:3] == [(), ("Cost",), ("Hygiene", "Cost")]


def test_the_final_analysis_has_the_last_word_on_every_line():
    complaints = _Detections()
    workflow, call_service = _workflow(complaints)
    for index, (role, text) in enumerate(LINES, start=1):
        call_service.add_utterance(CALL_ID, _utterance(index, role, text))
    complaints.results = [_detection("Cost", 3)]
    workflow.analyze_latest_speech(CALL_ID)

    complaints.results = [_detection("Cost", 2), _detection("Turnaround Time", 3)]
    workflow.complete_call(CALL_ID, 30.0)

    assert _tags(call_service.get_call(CALL_ID)) == [(), ("Cost",), ("Turnaround Time",), ()]


def test_the_combined_live_request_tags_lines_in_the_same_request():
    combined = {
        "complaints": [_item("Cost", [2]), _item("Hygiene", [3])],
        "sentiment": {"label": "NEGATIVE", "confidence": 0.9, "evidence": "Unhappy."},
        "escalation": {"signals": []},
    }
    llm = _LLM(combined)
    complaints, sentiment = LLMComplaintProvider(llm), LLMSentimentProvider(llm)
    service = ConversationAnalysisService(
        ComplaintAnalysisService(complaints),
        SentimentAnalysisService(sentiment),
        live_analyzer=LLMLiveAnalysisProvider(llm, complaints, sentiment, LLMEscalationProvider(llm)),
    )
    # Every line already has a tone: the transcript is numbered all the same.
    call = _conversation()
    call.annotate_utterances(
        [
            UtteranceSentiment(u.utterance_id, SentimentLabel.NEUTRAL, 0.5, u.transcript)
            for u in call.utterances
        ]
    )

    result = service.analyze(call, ConversationCoverage(CALL_ID), live=True)

    assert len(llm.prompts) == 1
    assert "[3] CUSTOMER: And the car came back dirty" in llm.prompts[0]
    assert [t.categories for t in result.line_categories] == [(), ("Cost",), ("Hygiene",), ()]


# ---- In the database and the API ----


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield build_session_factory(engine)
    engine.dispose()


def test_line_categories_are_stored_in_the_database_and_shown_by_the_api(session_factory):
    service = CallService(ConversationService(PostgresConversationRepository(session_factory)))
    service.start_call(CALL_ID)
    for index, (role, text) in enumerate(LINES, start=1):
        service.add_utterance(CALL_ID, _utterance(index, role, text))
    lines = service.get_call(CALL_ID).utterances

    service.annotate_utterances(
        CALL_ID, categories=[_entry(lines[1], "Cost"), _entry(lines[2], "Hygiene", "Turnaround Time")]
    )

    stored = service.get_call(CALL_ID)
    assert _tags(stored) == [(), ("Cost",), ("Hygiene", "Turnaround Time"), ()]
    shown = to_call_response(stored).model_dump()["utterances"]
    assert [(u["complaint_categories"], u["multi_category"]) for u in shown] == [
        ([], False),
        (["Cost"], False),
        (["Hygiene", "Turnaround Time"], True),
        ([], False),
    ]


# ---- In reports: the customer's own words ----


def test_the_first_line_raising_a_category_is_its_quote():
    quotes = first_quotes(
        [
            ("Hello.", None),
            ("  The bill was too high.  ", ["Cost"]),
            ("Dirty and late, and still too costly.", ["Hygiene", "Cost"]),
            ("x" * 400, ["Communication"]),
        ]
    )

    assert quotes["Cost"] == "The bill was too high."
    assert quotes["Hygiene"] == "Dirty and late, and still too costly."
    assert len(quotes["Communication"]) == MAX_QUOTE_CHARS and quotes["Communication"].endswith("…")


DAY = 86400.0
START = 1767551400.0


def _summary(call_id: str, described: dict[str, str]) -> PostCallSummary:
    return PostCallSummary(
        call_id=call_id,
        overall_summary="A call.",
        languages=("en",),
        sentiment=SentimentResult(SentimentLabel.NEGATIVE, 0.9, "What was said."),
        complaints=tuple(
            ComplaintSummary(category, text, ComplaintCoverageStatus.DETECTED, "Evidence.")
            for category, text in described.items()
        ),
        unresolved_issues=(),
        actions_promised=(),
        follow_up_required=False,
        customer_summary="A summary.",
    )


@pytest.fixture(params=["memory", "sql"])
def report(request, session_factory):
    """A report over three calls about cost: two described by their
    summaries, one only by what the customer said."""
    if request.param == "memory":
        conversations = InMemoryConversationRepository()
        coverages = InMemoryConversationCoverageRepository()
        summaries = InMemoryPostCallSummaryRepository()
        source = InMemoryReportSource(conversations, coverages, summaries)
    else:
        conversations = PostgresConversationRepository(session_factory)
        coverages = PostgresConversationCoverageRepository(session_factory)
        summaries = PostgresPostCallSummaryRepository(session_factory)
        source = PostgresReportSource(session_factory)

    def call(call_id: str, day: int, said: str | None, described: str | None) -> None:
        conversation = Conversation(call_id, start_time=START + day * DAY)
        conversation.add_utterance(_utterance(1, SpeakerRole.ICR, "How can I help?"))
        if said is not None:
            line = _utterance(2, SpeakerRole.CUSTOMER, said)
            conversation.add_utterance(line)
            conversation.annotate_utterances(categories=[_entry(line, "Cost")])
        # Utterance ids are unique across calls in the database.
        conversation.replace_transcript(
            tuple(
                Utterance(
                    f"{call_id}-{u.utterance_id}",
                    u.transcript,
                    u.speaker_role,
                    u.languages,
                    u.start_time,
                    u.end_time,
                    complaint_categories=u.complaint_categories,
                )
                for u in conversation.utterances
            )
        )
        conversations.add(conversation)
        coverage = ConversationCoverage(call_id)
        coverage.add("Cost").detect()
        coverages.save(coverage)
        if described is not None:
            summaries.add_if_absent(_summary(call_id, {"Cost": described}))

    call("c1", 1, "You charged me 14,000 against a quote of 8,000.", "The final bill was higher than the estimate.")
    call("c2", 2, None, "The final bill was much higher than the estimate given.")
    call("c3", 3, "The labour charges are far too costly.", None)
    service = ReportService(source)
    return service.complaint_report(ReportFilters(START, START + 14 * DAY), None, 330)


def test_a_root_cause_quotes_the_customer_and_fewer_complaints_go_undescribed(report):
    (cost,) = report.root_causes

    # c3 has no summary: what the customer said describes it.
    assert (cost.complaints, cost.undescribed) == (3, 0)
    themes = {theme.text: theme for theme in cost.themes}
    billed = themes["The final bill was higher than the estimate."]
    assert (billed.complaints, billed.quote) == (
        2,
        "You charged me 14,000 against a quote of 8,000.",
    )
    spoken = themes["The labour charges are far too costly."]
    assert (spoken.complaints, spoken.quote) == (1, "The labour charges are far too costly.")
    assert {row.call_id: row.quote for row in report.rows} == {
        "c1": "You charged me 14,000 against a quote of 8,000.",
        "c2": None,
        "c3": "The labour charges are far too costly.",
    }


def test_the_spreadsheet_exports_carry_the_customers_words(report):
    csv_text = export_report(report, "csv")[0].decode("utf-8-sig")

    header, first = csv_text.splitlines()[:2]
    assert header.endswith("Description,Customer's words")
    assert first.endswith('"You charged me 14,000 against a quote of 8,000."')
    assert export_report(report, "xlsx")[0][:2] == b"PK"
