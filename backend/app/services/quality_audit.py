"""Quality audit: a score for how each call was handled, with a score per
complaint category raised on it.

Worked out by the fixed rules below from what the call already stores
(whether each complaint was asked about, what the executive did with the
questions suggested for it, where the complaint stands now, how the
customer's tone moved, an escalation left open, time on hold). No AI model
is asked, and nobody listened to the call: the score is an estimate and is
shown as one. The rules are written out for the reader on the call's audit
panel and on the Reports page: keep them in step.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from app.domain.escalation import EscalationLevel
from app.services.reporting import ReportCall, ReportComplaint, tone_change

# ---- A complaint category: points for each thing done about it ----

# The executive asked the customer about the complaint.
ASKED_ABOUT_POINTS = 60
# Of the questions suggested about it, the executive accepted at least one.
# Not counted when none was suggested (or none was answered either way).
USED_SUGGESTION_POINTS = 20
# The complaint has since been resolved.
RESOLVED_POINTS = 20

# ---- The call as a whole: added to the average of its categories ----

# The customer ended in a milder tone than they began, or a harsher one.
TONE_IMPROVED_POINTS = 5
TONE_WORSENED_POINTS = -10
# A high or critical escalation nobody has resolved.
OPEN_ESCALATION_POINTS = -10
# The customer was kept on hold longer than this, in all.
LONG_HOLD_SECONDS = 120.0
LONG_HOLD_POINTS = -5

# A call that raised no complaint starts from this.
NO_COMPLAINT_SCORE = 100.0
# A detection the model was this unsure of is flagged beside its score
# (the score itself is about what the executive did, not the detector).
UNSURE_BELOW = 0.6

_RESOLVED = "resolved"
_SERIOUS = frozenset({EscalationLevel.HIGH, EscalationLevel.CRITICAL})


@dataclass(frozen=True)
class AuditPoint:
    """One rule as it applied: what it is about, the points earned and the
    most it could have earned (0 both ways for a deduction not made)."""

    rule: str
    points: float
    possible: float
    note: str


@dataclass(frozen=True)
class CategoryAudit:
    category: str
    # 0 to 100.
    score: float
    points: tuple[AuditPoint, ...]
    # The detector was not sure this complaint was raised at all.
    unsure: bool = False


@dataclass(frozen=True)
class CallAudit:
    call_id: str
    # 0 to 100.
    score: float
    categories: tuple[CategoryAudit, ...]
    # The call-level rules that added or took points.
    adjustments: tuple[AuditPoint, ...]


def audit_category(complaint: ReportComplaint) -> CategoryAudit:
    points = [
        AuditPoint(
            "asked_about",
            ASKED_ABOUT_POINTS if complaint.probed else 0,
            ASKED_ABOUT_POINTS,
            "The executive asked about it."
            if complaint.probed
            else "The executive did not ask about it.",
        )
    ]
    suggested = complaint.questions_accepted + complaint.questions_skipped
    if suggested:
        used = complaint.questions_accepted > 0
        points.append(
            AuditPoint(
                "used_suggestion",
                USED_SUGGESTION_POINTS if used else 0,
                USED_SUGGESTION_POINTS,
                f"Accepted {complaint.questions_accepted} of {suggested} suggested "
                f"question{'' if suggested == 1 else 's'}."
                if used
                else f"Skipped every suggested question ({suggested}).",
            )
        )
    resolved = complaint.status == _RESOLVED
    points.append(
        AuditPoint(
            "resolved",
            RESOLVED_POINTS if resolved else 0,
            RESOLVED_POINTS,
            "The complaint has been resolved."
            if resolved
            else "The complaint has not been resolved yet.",
        )
    )
    possible = sum(point.possible for point in points)
    return CategoryAudit(
        category=complaint.category,
        score=round(100 * sum(point.points for point in points) / possible, 1),
        points=tuple(points),
        unsure=complaint.confidence is not None and complaint.confidence < UNSURE_BELOW,
    )


def _adjustments(call: ReportCall) -> tuple[AuditPoint, ...]:
    found = []
    change = tone_change(call)
    if change is not None and change < 0:
        found.append(
            AuditPoint(
                "tone",
                TONE_IMPROVED_POINTS,
                0,
                "The customer ended in a milder tone than they began.",
            )
        )
    elif change:
        found.append(
            AuditPoint(
                "tone",
                TONE_WORSENED_POINTS,
                0,
                "The customer ended in a harsher tone than they began.",
            )
        )
    if call.escalation_open and call.escalation_level in _SERIOUS:
        found.append(
            AuditPoint(
                "open_escalation",
                OPEN_ESCALATION_POINTS,
                0,
                f"A {call.escalation_level.value} escalation has not been resolved.",
            )
        )
    if call.hold_seconds > LONG_HOLD_SECONDS:
        found.append(
            AuditPoint(
                "long_hold",
                LONG_HOLD_POINTS,
                0,
                f"The customer was on hold for {round(call.hold_seconds)} seconds in all.",
            )
        )
    return tuple(found)


def audit_call(call: ReportCall) -> CallAudit:
    categories = tuple(audit_category(complaint) for complaint in call.complaints)
    adjustments = _adjustments(call)
    base = (
        sum(category.score for category in categories) / len(categories)
        if categories
        else NO_COMPLAINT_SCORE
    )
    score = base + sum(point.points for point in adjustments)
    return CallAudit(
        call_id=call.call_id,
        score=round(min(100.0, max(0.0, score)), 1),
        categories=categories,
        adjustments=adjustments,
    )


@dataclass(frozen=True)
class AuditFigures:
    """The audit over a set of calls. Calls that raised no complaint are
    left out: there was nothing to handle well or badly on them."""

    audited_calls: int
    # The average call score; None when no call raised a complaint.
    score: float | None
    # The category handled worst on average, with that average; None when
    # no call raised a complaint.
    weakest_category: str | None
    weakest_category_score: float | None


def audit_figures(calls: Iterable[ReportCall]) -> AuditFigures:
    scores: list[float] = []
    by_category: dict[str, list[float]] = defaultdict(list)
    for call in calls:
        if not call.complaints:
            continue
        audit = audit_call(call)
        scores.append(audit.score)
        for category in audit.categories:
            by_category[category.category].append(category.score)
    if not scores:
        return AuditFigures(0, None, None, None)
    averages = {
        category: sum(values) / len(values) for category, values in by_category.items()
    }
    # The lowest average; among equals, the one raised most, then by name.
    weakest = min(
        averages, key=lambda c: (averages[c], -len(by_category[c]), c.casefold())
    )
    return AuditFigures(
        audited_calls=len(scores),
        score=round(sum(scores) / len(scores), 1),
        weakest_category=weakest,
        weakest_category_score=round(averages[weakest], 1),
    )
