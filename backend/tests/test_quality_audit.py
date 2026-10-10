"""Quality audit and sentiment trends: a score per call and per complaint
category by fixed rules, the audit on the executives' scorecard, how calls
ended and changed in reports, the tone trend overall and per executive, and
that both report sources supply what all of it is worked out from."""

import csv
import io
import time

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
    UtteranceSentiment,
)
from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.core.config import Settings
from app.domain.call_alert import QuestionOutcome, QuestionOutcomeChoice
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.escalation import (
    Escalation,
    EscalationLevel,
    EscalationSignal,
    EscalationSignalType,
    EscalationStatus,
)
from app.domain.post_call_summary import PostCallSummary
from app.domain.user import User, UserRole
from app.domain.utterance import SpeakerRole, Utterance
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import build_session_factory
from app.infrastructure.database.repositories.call_alert_repository import (
    PostgresQuestionOutcomeRepository,
)
from app.infrastructure.database.repositories.conversation_coverage_repository import (
    PostgresConversationCoverageRepository,
)
from app.infrastructure.database.repositories.conversation_repository import (
    PostgresConversationRepository,
)
from app.infrastructure.database.repositories.escalation_repository import (
    PostgresEscalationRepository,
)
from app.infrastructure.database.repositories.post_call_summary_repository import (
    PostgresPostCallSummaryRepository,
)
from app.infrastructure.database.repositories.report_source import PostgresReportSource
from app.security.jwt import create_access_token
from app.services.call_alerts import InMemoryQuestionOutcomeRepository
from app.services.escalation_repository import InMemoryEscalationRepository
from app.services.in_memory_conversation_coverage_repository import (
    InMemoryConversationCoverageRepository,
)
from app.services.in_memory_conversation_repository import InMemoryConversationRepository
from app.services.performance import PerformanceService
from app.services.post_call_summary_repository import InMemoryPostCallSummaryRepository
from app.services.quality_audit import (
    LONG_HOLD_SECONDS,
    audit_call,
    audit_category,
    audit_figures,
)
from app.services.report_export import export_report, export_scorecard
from app.services.reporting import (
    InMemoryReportSource,
    ReportCall,
    ReportComplaint,
    ReportFilters,
    ReportService,
    ReportSource,
    TonePoint,
    tone_change,
)

DAY = 86400.0
IST = 330
# Monday 5 January 2026, 00:00 in India.
START = 1767551400.0
POSITIVE, NEUTRAL, NEGATIVE = SentimentLabel.POSITIVE, SentimentLabel.NEUTRAL, SentimentLabel.NEGATIVE
FRUSTRATED, ESCALATING = SentimentLabel.FRUSTRATED, SentimentLabel.ESCALATING


def _complaint(category: str = "Cost", status: str = "detected", probed: bool = False, **more):
    return ReportComplaint(category, status, None, probed, **more)


def _call(call_id: str = "c1", *complaints: ReportComplaint, day: float = 1, **fields) -> ReportCall:
    return ReportCall(call_id, START + day * DAY, complaints=tuple(complaints), **fields)


def _points(audit) -> dict[str, float]:
    return {point.rule: point.points for point in audit.points}


# ---- A complaint category ----


def test_a_complaint_nobody_asked_about_scores_nothing():
    audit = audit_category(_complaint())

    assert audit.score == 0.0
    assert _points(audit) == {"asked_about": 0, "resolved": 0}
    assert audit.points[0].note == "The executive did not ask about it."


def test_asking_about_a_complaint_earns_most_of_its_score():
    audit = audit_category(_complaint(probed=True))

    # 60 of the 80 that apply: no question was suggested about it.
    assert (audit.score, _points(audit)) == (75.0, {"asked_about": 60, "resolved": 0})


def test_a_complaint_asked_about_and_since_resolved_scores_in_full():
    assert audit_category(_complaint(status="resolved", probed=True)).score == 100.0


@pytest.mark.parametrize(
    ("accepted", "skipped", "points", "score"),
    [
        (1, 0, 20, 80.0),
        (2, 3, 20, 80.0),
        # Every suggestion skipped: the rule applies and earns nothing.
        (0, 2, 0, 60.0),
    ],
)
def test_using_a_suggested_question_counts_when_one_was_suggested(accepted, skipped, points, score):
    audit = audit_category(
        _complaint(probed=True, questions_accepted=accepted, questions_skipped=skipped)
    )

    assert _points(audit)["used_suggestion"] == points
    assert audit.score == score


def test_an_unsure_detection_is_flagged_not_scored():
    unsure = audit_category(_complaint(probed=True, confidence=0.4))
    sure = audit_category(_complaint(probed=True, confidence=0.9))

    assert (unsure.unsure, sure.unsure) == (True, False)
    assert unsure.score == sure.score
    assert audit_category(_complaint(probed=True)).unsure is False


# ---- The call ----


def test_a_calls_score_is_the_average_of_its_categories():
    audit = audit_call(
        _call("c1", _complaint("Cost", "resolved", True), _complaint("Hygiene", "detected", False))
    )

    assert [(c.category, c.score) for c in audit.categories] == [("Cost", 100.0), ("Hygiene", 0.0)]
    assert (audit.score, audit.adjustments) == (50.0, ())


@pytest.mark.parametrize(
    ("start", "end", "change"),
    [
        (NEGATIVE, POSITIVE, -1),
        (FRUSTRATED, NEUTRAL, -1),
        (NEUTRAL, ESCALATING, 1),
        (NEGATIVE, NEGATIVE, 0),
        (None, NEGATIVE, None),
        (None, None, None),
    ],
)
def test_the_tone_ends_milder_harsher_or_the_same(start, end, change):
    assert tone_change(_call(tone_start=start, tone_end=end)) == change


def test_what_happened_on_the_call_as_a_whole_moves_its_score():
    base = _complaint(probed=True)  # 75

    calmer = audit_call(_call("c", base, tone_start=FRUSTRATED, tone_end=NEUTRAL))
    assert (calmer.score, [p.rule for p in calmer.adjustments]) == (80.0, ["tone"])

    worse = audit_call(
        _call(
            "c",
            base,
            tone_start=NEUTRAL,
            tone_end=ESCALATING,
            escalation_level=EscalationLevel.CRITICAL,
            escalation_open=True,
            hold_seconds=LONG_HOLD_SECONDS + 1,
        )
    )
    assert (worse.score, [(p.rule, p.points) for p in worse.adjustments]) == (
        50.0,
        [("tone", -10), ("open_escalation", -10), ("long_hold", -5)],
    )
    assert "121 seconds" in worse.adjustments[2].note


def test_a_resolved_or_minor_escalation_and_a_short_hold_cost_nothing():
    base = _complaint(probed=True)

    for fields in (
        {"escalation_level": EscalationLevel.CRITICAL, "escalation_open": False},
        {"escalation_level": EscalationLevel.WATCH, "escalation_open": True},
        {"hold_seconds": LONG_HOLD_SECONDS},
        {"tone_start": NEGATIVE, "tone_end": NEGATIVE},
    ):
        assert audit_call(_call("c", base, **fields)).adjustments == ()


def test_a_score_stays_between_0_and_100():
    worst = audit_call(
        _call(
            "c",
            _complaint(),
            tone_start=POSITIVE,
            tone_end=ESCALATING,
            escalation_level=EscalationLevel.HIGH,
            escalation_open=True,
        )
    )
    best = audit_call(
        _call("c", _complaint(status="resolved", probed=True), tone_start=NEGATIVE, tone_end=POSITIVE)
    )

    assert (worst.score, best.score) == (0.0, 100.0)


def test_a_call_with_no_complaint_is_scored_on_the_call_alone():
    assert audit_call(_call()).score == 100.0
    assert audit_call(_call(tone_start=NEUTRAL, tone_end=NEGATIVE)).score == 90.0


# ---- Over many calls ----


def test_the_audit_over_calls_averages_those_that_raised_a_complaint():
    figures = audit_figures(
        [
            _call("a", _complaint("Cost", "resolved", True), _complaint("Hygiene")),  # 50
            _call("b", _complaint("Cost", "detected", True)),  # 75
            _call("c", _complaint("Hygiene", "detected", True)),  # 75
            _call("quiet"),  # no complaint: not audited
        ]
    )

    assert (figures.audited_calls, figures.score) == (3, 66.7)
    # Hygiene: (0 + 75) / 2; Cost: (100 + 75) / 2.
    assert (figures.weakest_category, figures.weakest_category_score) == ("Hygiene", 37.5)


def test_no_complaints_means_no_audit_score():
    figures = audit_figures([_call("quiet")])

    assert (figures.audited_calls, figures.score, figures.weakest_category) == (0, None, None)


# ---- The executives' scorecard and their tone trends ----


class _Calls(ReportSource):
    def __init__(self, *calls: ReportCall) -> None:
        self.all = list(calls)

    def calls(self, filters, limit):
        matching = [c for c in self.all if filters.started_from <= c.start_time < filters.started_to]
        return tuple(sorted(matching, key=lambda call: call.start_time)[:limit])

    def call(self, call_id):
        return next((c for c in self.all if c.call_id == call_id), None)


def _by(executive: str, call_id: str, day: float, tone, *complaints) -> ReportCall:
    return _call(
        call_id,
        *complaints,
        day=day,
        executive_user_id=executive,
        executive_name=executive.title(),
        sentiment=tone,
    )


def _performance(*calls: ReportCall, days: float = 3, **options):
    service = PerformanceService(_Calls(*calls), clock=lambda: START + 60 * DAY)
    return service.report(ReportFilters(START, START + days * DAY), tz_offset_minutes=IST, **options)


def test_the_scorecard_carries_each_executives_audit_and_weakest_category():
    report = _performance(
        _by("asha", "a1", 0.5, NEUTRAL, _complaint("Cost", "resolved", True)),
        _by("asha", "a2", 1.5, NEGATIVE, _complaint("Hygiene")),
        _by("ravi", "r1", 0.5, POSITIVE),
    )

    figures = {e.name: e.figures for e in report.executives}
    assert (figures["Asha"].audited_calls, figures["Asha"].audit_score) == (2, 50.0)
    assert (figures["Asha"].weakest_category, figures["Asha"].weakest_category_score) == (
        "Hygiene",
        0.0,
    )
    assert (figures["Ravi"].audited_calls, figures["Ravi"].audit_score) == (0, None)
    assert report.overall.audit_score == 50.0


def test_the_tone_trend_is_per_day_for_everyone_and_for_each_executive():
    report = _performance(
        _by("asha", "a1", 0.5, NEUTRAL),
        _by("asha", "a2", 0.6, FRUSTRATED),
        _by("asha", "a3", 2.5, None),  # no tone yet: not in the trend
        _by("ravi", "r1", 1.5, NEGATIVE),
    )

    assert report.bucket == "day"
    assert report.bucket_starts == (START, START + DAY, START + 2 * DAY)
    assert report.tone_trend == (TonePoint(2, 1), TonePoint(1, 1), TonePoint(0, 0))
    trends = {e.name: e.tone_trend for e in report.executives}
    assert trends["Asha"] == (TonePoint(2, 1), TonePoint(0, 0), TonePoint(0, 0))
    assert trends["Ravi"] == (TonePoint(0, 0), TonePoint(1, 1), TonePoint(0, 0))


def test_a_long_period_is_trended_by_week_unless_asked_otherwise():
    calls = (_by("asha", "a1", 1, NEGATIVE), _by("asha", "a2", 70, POSITIVE))

    assert _performance(*calls, days=90).bucket == "week"
    assert _performance(*calls, days=90, bucket="day").bucket == "day"


def test_one_calls_audit_can_be_looked_up():
    service = PerformanceService(_Calls(_by("asha", "a1", 1, NEUTRAL, _complaint(probed=True))))

    assert service.audit("a1").score == 75.0
    assert service.audit("nope") is None


def test_the_scorecard_exports_carry_the_audit_and_the_tone_trend():
    report = _performance(
        _by("asha", "a1", 0.5, NEGATIVE, _complaint("Cost", "detected", True)),
        _by("asha", "a2", 1.5, NEUTRAL),
    )

    rows = list(csv.reader(io.StringIO(export_scorecard(report, "csv", IST)[0].decode("utf-8-sig"))))
    assert rows[0][-4:] == [
        "Audit score 0-100 (estimate)",
        "Calls audited",
        "Weakest category",
        "Weakest category score",
    ]
    assert rows[1][-4:] == ["75.0", "1", "Cost", "75.0"]

    workbook = load_workbook(io.BytesIO(export_scorecard(report, "xlsx", IST)[0]))
    assert workbook.sheetnames == ["Scorecard", "Tone trend"]
    trend = list(workbook["Tone trend"].iter_rows(values_only=True))
    assert trend[0][1:] == ("05 Jan 2026", "06 Jan 2026", "07 Jan 2026")
    # A day with no rated call has no share.
    assert trend[1] == ("Asha", 100, 0, None)
    assert trend[2][0] == "All executives"


# ---- Reports: how calls ended, and both sources ----


def _summary(call_id: str, tone: SentimentLabel) -> PostCallSummary:
    return PostCallSummary(
        call_id=call_id,
        overall_summary="A call.",
        languages=("en",),
        sentiment=SentimentResult(tone, 0.9, "What was said."),
        complaints=(),
        unresolved_issues=(),
        actions_promised=(),
        follow_up_required=False,
        customer_summary="A summary.",
    )


class _Stores:
    def __init__(self, session_factory=None) -> None:
        if session_factory is None:
            self.conversations = InMemoryConversationRepository()
            self.coverages = InMemoryConversationCoverageRepository()
            self.summaries = InMemoryPostCallSummaryRepository()
            self.escalations = InMemoryEscalationRepository()
            self.outcomes = InMemoryQuestionOutcomeRepository()
            self.source = InMemoryReportSource(
                self.conversations,
                self.coverages,
                self.summaries,
                escalations=self.escalations,
                question_outcomes=self.outcomes,
            )
        else:
            self.conversations = PostgresConversationRepository(session_factory)
            self.coverages = PostgresConversationCoverageRepository(session_factory)
            self.summaries = PostgresPostCallSummaryRepository(session_factory)
            self.escalations = PostgresEscalationRepository(session_factory)
            self.outcomes = PostgresQuestionOutcomeRepository(session_factory)
            self.source = PostgresReportSource(session_factory)

    def call(self, call_id: str, day: float, ended: SentimentLabel | None, line_tones=()) -> Conversation:
        """A call whose customer's lines carry `line_tones` (None: not
        rated), ending on `ended` overall."""
        conversation = Conversation(call_id, start_time=START + day * DAY)
        ratings = []
        for index, tone in enumerate(line_tones):
            line = Utterance(
                f"{call_id}-u{index}", "Hello.", SpeakerRole.CUSTOMER, ("en",), index, index + 0.5
            )
            conversation.add_utterance(line)
            if tone is not None:
                ratings.append(UtteranceSentiment(line.utterance_id, tone, 0.8, line.transcript))
        conversation.rate_utterances(ratings)
        self.conversations.add(conversation)
        if ended is not None:
            self.summaries.add_if_absent(_summary(call_id, ended))
        return conversation


@pytest.fixture(params=["memory", "sql"])
def stores(request) -> _Stores:
    if request.param == "memory":
        return _Stores()
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    request.addfinalizer(engine.dispose)
    return _Stores(build_session_factory(engine))


def test_the_sources_supply_what_the_audit_is_worked_out_from(stores):
    conversation = stores.call("c1", 1, NEGATIVE, [None, FRUSTRATED, NEGATIVE, None, NEUTRAL])
    conversation.hold(10.0)
    conversation.resume(55.0)
    stores.conversations.save(conversation)
    coverage = ConversationCoverage("c1")
    cost = coverage.add("Cost")
    cost.detect()
    cost.probe()
    cost.confidence = 0.45
    coverage.add("Hygiene").detect()
    stores.coverages.save(coverage)
    stores.escalations.save(
        Escalation(
            "c1",
            EscalationLevel.HIGH,
            (EscalationSignal(EscalationSignalType.OTHER, EscalationLevel.HIGH, "Asked for a manager."),),
            EscalationStatus.OPEN,
            1.0,
            1.0,
        )
    )
    for question, category, choice in (
        ("What were you quoted?", "Cost", QuestionOutcomeChoice.ACCEPTED),
        ("What were you billed?", "Cost", QuestionOutcomeChoice.SKIPPED),
        ("What was dirty?", "Hygiene", QuestionOutcomeChoice.SKIPPED),
    ):
        stores.outcomes.save(QuestionOutcome("c1", question, category, choice, "asha", 5.0))
    stores.call("quiet", 2, None)

    call = stores.source.call("c1")

    assert (call.tone_start, call.tone_end, call.hold_seconds) == (FRUSTRATED, NEUTRAL, 45.0)
    assert (call.escalation_level, call.escalation_open) == (EscalationLevel.HIGH, True)
    assert (call.questions_accepted, call.questions_skipped) == (1, 2)
    by_category = {c.category: c for c in call.complaints}
    assert (
        by_category["Cost"].probed,
        by_category["Cost"].confidence,
        by_category["Cost"].questions_accepted,
        by_category["Cost"].questions_skipped,
    ) == (True, 0.45, 1, 1)
    assert (by_category["Hygiene"].probed, by_category["Hygiene"].questions_skipped) == (False, 1)
    # Listed with the others exactly as it is looked up alone.
    listed = stores.source.calls(ReportFilters(START, START + 7 * DAY), 50)
    assert [c.call_id for c in listed] == ["c1", "quiet"]
    assert listed[0] == call
    quiet = listed[1]
    assert (quiet.tone_start, quiet.tone_end, quiet.hold_seconds, quiet.escalation_open) == (
        None,
        None,
        0.0,
        False,
    )
    assert stores.source.call("nope") is None

    # Cost: asked about (60) + a suggestion used (20) of 100; Hygiene: none of 80.
    audit = audit_call(call)
    assert [(c.category, c.score, c.unsure) for c in audit.categories] == [
        ("Cost", 80.0, True),
        ("Hygiene", 0.0, False),
    ]
    # 40 on average, +5 for the milder ending, -10 for the open escalation.
    assert audit.score == 35.0


def test_a_report_says_how_calls_ended_and_how_they_changed(stores):
    stores.call("better", 0.5, NEUTRAL, [FRUSTRATED, NEUTRAL])
    stores.call("worse", 0.6, ESCALATING, [NEUTRAL, None, ESCALATING])
    stores.call("same", 1.5, NEGATIVE, [NEGATIVE, NEGATIVE])
    stores.call("old", 1.6, POSITIVE)  # from before lines carried tones
    stores.call("unrated", 2.5, None)

    report = ReportService(stores.source).complaint_report(
        ReportFilters(START, START + 3 * DAY), None, IST
    )

    tone = report.tone
    assert (tone.rated_calls, tone.negative_calls) == (4, 2)
    assert {count.label: count.calls for count in tone.by_tone} == {
        POSITIVE: 1,
        NEUTRAL: 1,
        NEGATIVE: 1,
        FRUSTRATED: 0,
        ESCALATING: 1,
    }
    assert [count.label for count in tone.by_tone] == [
        POSITIVE,
        NEUTRAL,
        NEGATIVE,
        FRUSTRATED,
        ESCALATING,
    ]
    assert (tone.tracked_calls, tone.improved_calls, tone.worsened_calls) == (3, 1, 1)
    # One point per day of the report, like the complaint trend.
    assert tone.trend == (TonePoint(2, 1), TonePoint(2, 1), TonePoint(0, 0))
    assert len(tone.trend) == len(report.bucket_starts)

    workbook = load_workbook(io.BytesIO(export_report(report, "xlsx")[0]))
    summary = dict(workbook["Tone"].iter_rows(values_only=True))
    assert (summary["Escalating"], summary["Customer ended milder than they began"]) == (1, 1)
    trend = list(workbook["Tone trend"].iter_rows(values_only=True))
    assert trend[3] == ("% negative or worse", 50, 50, None)


# ---- The API ----


class _NoComplaints(ComplaintDetectionProvider):
    def detect(self, conversation, learning_context=()):
        return []


class _Calm(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(NEUTRAL, 0.7, "Calm.")


class _NoQuestions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


def test_supervisors_see_a_calls_audit_and_the_trends_and_executives_do_not():
    services = build_api_services(
        _NoComplaints(), _Calm(), _NoQuestions(), Settings(_env_file=None)  # type: ignore[call-arg]
    )
    client = TestClient(create_app(services))

    def sign_in(user_id: str, role: UserRole) -> dict[str, str]:
        user = User(user_id, f"{user_id}@example.com", "hash", role, True, time.time())
        services.user_repository.save(user)
        return {"Authorization": f"Bearer {create_access_token(user)}"}

    asha, supervisor = sign_in("asha", UserRole.ICR), sign_in("sup", UserRole.SUPERVISOR)
    client.post("/api/v1/calls", json={"call_id": "c1", "start_time": None}, headers=asha)
    coverage = ConversationCoverage("c1")
    complaint = coverage.add("Cost")
    complaint.detect()
    complaint.probe()
    services.workflow_service._coverage_repository.save(coverage)

    audit = client.get("/api/v1/reports/calls/c1/audit", headers=supervisor)
    assert audit.status_code == 200
    body = audit.json()
    assert (body["call_id"], body["score"], body["adjustments"]) == ("c1", 75.0, [])
    (category,) = body["categories"]
    assert (category["category"], category["score"], category["unsure"]) == ("Cost", 75.0, False)
    assert [(p["rule"], p["points"], p["possible"]) for p in category["points"]] == [
        ("asked_about", 60, 60),
        ("resolved", 0, 20),
    ]
    assert client.get("/api/v1/reports/calls/nope/audit", headers=supervisor).status_code == 404
    assert client.get("/api/v1/reports/calls/c1/audit", headers=asha).status_code == 403

    performance = client.get(
        "/api/v1/reports/performance", params={"tz_offset_minutes": IST}, headers=supervisor
    ).json()
    assert (performance["overall"]["audit_score"], performance["overall"]["weakest_category"]) == (
        75.0,
        "Cost",
    )
    assert performance["bucket"] == "day"
    assert len(performance["tone_trend"]) == len(performance["bucket_starts"])
    assert len(performance["executives"][0]["tone_trend"]) == len(performance["bucket_starts"])

    complaints = client.get("/api/v1/reports/complaints", headers=supervisor).json()
    assert complaints["tone"]["rated_calls"] == 0
    assert len(complaints["tone"]["trend"]) == len(complaints["bucket_starts"])
