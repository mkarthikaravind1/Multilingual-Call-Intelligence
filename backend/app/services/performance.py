"""Management figures: how well executives cover complaints, whether a
first call settled the matter, repeat complaints, and estimates of churn
risk and customer satisfaction.

Every figure is worked out by the fixed rules below from what calls already
store. None is measured (nobody asked the customer), so each is an estimate
and is shown as one. The rules are written out for the reader on the
Reports page: keep the two in step.
"""

import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from app.domain.escalation import EscalationLevel
from app.domain.sentiment import SentimentLabel
from app.services.reporting import (
    MAX_REPORT_CALLS,
    SECONDS_PER_DAY,
    ReportCall,
    ReportError,
    ReportFilters,
    ReportSource,
)

# First Call Resolution: the matter was settled by one call when the same
# customer did not call again about the same category within this long.
FCR_WINDOW_DAYS = 7
# A complaint is a repeat when the same customer raised the same category
# within this long before it.
REPEAT_WINDOW_DAYS = 30

_RESOLVED = "resolved"
_SERIOUS_ESCALATIONS = frozenset({EscalationLevel.HIGH, EscalationLevel.CRITICAL})

# Churn risk: points per sign, and the totals at which the risk steps up.
_CHURN_TONE_POINTS = {
    SentimentLabel.NEGATIVE: 1,
    SentimentLabel.FRUSTRATED: 2,
    SentimentLabel.ESCALATING: 3,
}
CHURN_ESCALATION_POINTS = 2
CHURN_REPEAT_POINTS = 2
CHURN_OPEN_COMPLAINT_POINTS = 1
CHURN_MEDIUM_FROM = 2
CHURN_HIGH_FROM = 4

# CSAT estimate (1 to 5): where each tone starts, and what moves it.
_CSAT_BY_TONE = {
    SentimentLabel.POSITIVE: 4.5,
    SentimentLabel.NEUTRAL: 3.5,
    SentimentLabel.NEGATIVE: 2.5,
    SentimentLabel.FRUSTRATED: 2.0,
    SentimentLabel.ESCALATING: 1.5,
}
CSAT_OPEN_COMPLAINT = -0.5
CSAT_SERIOUS_ESCALATION = -0.5
CSAT_ALL_RESOLVED = 0.5

ChurnRisk = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class CallFigures:
    """One call's part in the figures."""

    call: ReportCall
    # Complaints from a customer who raised the same category recently.
    repeat_complaints: int
    # None: not counted (the customer is not known, the call raised no
    # complaint, or it is too recent to tell).
    resolved_first_time: bool | None
    churn_risk: ChurnRisk
    # None: the call has no tone yet.
    csat: float | None


@dataclass(frozen=True)
class Figures:
    """The figures over a set of calls. A rate is None when nothing it is
    worked out from is there (e.g. no complaints: no coverage score)."""

    calls: int
    complaints: int
    # Of the complaints raised, those the executive asked about.
    probed_complaints: int
    coverage_score: float | None
    # Calls First Call Resolution could be judged on, and those it held for.
    fcr_calls: int
    fcr_resolved: int
    fcr_rate: float | None
    # Complaints from known customers, and the repeats among them.
    known_customer_complaints: int
    repeat_complaints: int
    repeat_rate: float | None
    churn_low: int
    churn_medium: int
    churn_high: int
    # Calls with a tone, those ending negative or worse, and the average
    # CSAT estimate over them.
    rated_calls: int
    negative_calls: int
    csat: float | None
    serious_escalations: int


@dataclass(frozen=True)
class ExecutiveFigures:
    # None: calls with no executive recorded.
    executive_user_id: str | None
    name: str
    figures: Figures


@dataclass(frozen=True)
class PerformanceReport:
    filters: ReportFilters
    overall: Figures
    # Most calls first.
    executives: tuple[ExecutiveFigures, ...]


class PerformanceService:
    def __init__(
        self,
        source: ReportSource,
        max_calls: int = MAX_REPORT_CALLS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._source = source
        self._max_calls = max_calls
        self._clock = clock

    def report(self, filters: ReportFilters) -> PerformanceReport:
        filters.require_reportable()
        calls = self._calls(filters)
        if filters.category is not None:
            calls = tuple(
                call for call in calls if any(c.category == filters.category for c in call.complaints)
            )
        # What each customer raised around the period, whoever took the
        # call: repeats look back, First Call Resolution looks ahead.
        history = self._calls(
            ReportFilters(
                filters.started_from - REPEAT_WINDOW_DAYS * SECONDS_PER_DAY,
                filters.started_to + FCR_WINDOW_DAYS * SECONDS_PER_DAY,
            )
        )
        raised = _raised_by_customer(history)
        now = self._clock()
        figures = [_call_figures(call, raised, now) for call in calls]

        by_executive: dict[str | None, list[CallFigures]] = defaultdict(list)
        names: dict[str | None, str] = {}
        for item in figures:
            by_executive[item.call.executive_user_id].append(item)
            names[item.call.executive_user_id] = item.call.executive_name or "Not recorded"
        return PerformanceReport(
            filters=filters,
            overall=_figures(figures),
            executives=tuple(
                ExecutiveFigures(user_id, names[user_id], _figures(items))
                for user_id, items in sorted(
                    by_executive.items(),
                    key=lambda entry: (
                        entry[0] is None,
                        -len(entry[1]),
                        names[entry[0]].casefold(),
                    ),
                )
            ),
        )

    def _calls(self, filters: ReportFilters) -> tuple[ReportCall, ...]:
        calls = self._source.calls(filters, self._max_calls + 1)
        if len(calls) > self._max_calls:
            raise ReportError(
                f"More than {self._max_calls:,} calls match. Choose a shorter date range "
                "or more filters."
            )
        return calls


def _raised_by_customer(calls: Iterable[ReportCall]) -> dict[tuple[str, str], list[float]]:
    """When each known customer raised each category (call start times)."""
    raised: dict[tuple[str, str], list[float]] = defaultdict(list)
    for call in calls:
        if call.customer_key is None:
            continue
        for complaint in call.complaints:
            raised[call.customer_key, complaint.category].append(call.start_time)
    return raised


def _call_figures(
    call: ReportCall, raised: dict[tuple[str, str], list[float]], now: float
) -> CallFigures:
    repeats = 0
    raised_again = False
    if call.customer_key is not None:
        for complaint in call.complaints:
            times = raised[call.customer_key, complaint.category]
            earliest = call.start_time - REPEAT_WINDOW_DAYS * SECONDS_PER_DAY
            repeats += any(earliest <= at < call.start_time for at in times)
            latest = call.start_time + FCR_WINDOW_DAYS * SECONDS_PER_DAY
            raised_again = raised_again or any(call.start_time < at <= latest for at in times)

    window_over = call.start_time + FCR_WINDOW_DAYS * SECONDS_PER_DAY <= now
    resolved_first_time = (
        not raised_again
        if call.customer_key is not None and call.complaints and window_over
        else None
    )
    serious = call.escalation_level in _SERIOUS_ESCALATIONS
    open_complaints = any(complaint.status != _RESOLVED for complaint in call.complaints)

    points = (
        _CHURN_TONE_POINTS.get(call.sentiment, 0)
        + (CHURN_ESCALATION_POINTS if serious else 0)
        + (CHURN_REPEAT_POINTS if repeats else 0)
        + (CHURN_OPEN_COMPLAINT_POINTS if open_complaints else 0)
    )
    churn: ChurnRisk = (
        "high" if points >= CHURN_HIGH_FROM else "medium" if points >= CHURN_MEDIUM_FROM else "low"
    )

    csat = None
    if call.sentiment is not None:
        csat = _CSAT_BY_TONE[call.sentiment]
        if open_complaints:
            csat += CSAT_OPEN_COMPLAINT
        elif call.complaints:
            csat += CSAT_ALL_RESOLVED
        if serious:
            csat += CSAT_SERIOUS_ESCALATION
        csat = min(5.0, max(1.0, csat))
    return CallFigures(call, repeats, resolved_first_time, churn, csat)


def _rate(part: int, whole: int) -> float | None:
    return None if whole == 0 else part / whole


def _figures(items: list[CallFigures]) -> Figures:
    complaints = sum(len(item.call.complaints) for item in items)
    probed = sum(c.probed for item in items for c in item.call.complaints)
    judged = [item for item in items if item.resolved_first_time is not None]
    fcr_resolved = sum(1 for item in judged if item.resolved_first_time)
    known = sum(len(item.call.complaints) for item in items if item.call.customer_key is not None)
    repeats = sum(item.repeat_complaints for item in items)
    rated = [item for item in items if item.csat is not None]
    return Figures(
        calls=len(items),
        complaints=complaints,
        probed_complaints=probed,
        coverage_score=_rate(probed, complaints),
        fcr_calls=len(judged),
        fcr_resolved=fcr_resolved,
        fcr_rate=_rate(fcr_resolved, len(judged)),
        known_customer_complaints=known,
        repeat_complaints=repeats,
        repeat_rate=_rate(repeats, known),
        churn_low=sum(1 for item in items if item.churn_risk == "low"),
        churn_medium=sum(1 for item in items if item.churn_risk == "medium"),
        churn_high=sum(1 for item in items if item.churn_risk == "high"),
        rated_calls=len(rated),
        negative_calls=sum(1 for item in rated if item.call.sentiment.is_negative),
        csat=None if not rated else round(sum(item.csat for item in rated) / len(rated), 2),
        serious_escalations=sum(
            1 for item in items if item.call.escalation_level in _SERIOUS_ESCALATIONS
        ),
    )
