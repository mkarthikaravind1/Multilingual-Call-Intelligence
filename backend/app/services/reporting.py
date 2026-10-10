"""Complaint reports for supervisors: how often each category comes up over
time and per location, and what the complaints in a category are about.

Everything is counted from what calls already store (their complaint
categories, post-call summary, location and executive). Nothing here asks
an AI model: the "root causes" are complaint descriptions grouped by
similar wording, by a fixed rule, each with the customer's own words from a
line of the call that raised it.
"""

import re
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Literal

from app.ai.sentiment.provider import SentimentLabel
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.complaint_lifecycle_repository import ComplaintLifecycleRepository
from app.domain.conversation import CallDirection
from app.domain.escalation import EscalationLevel
from app.domain.location import LocationRepository
from app.domain.user_repository import UserRepository
from app.services.call_alerts import QuestionOutcomeRepository, count_outcomes
from app.services.call_customer_repository import CallCustomerRepository
from app.services.conversation_coverage_repository import ConversationCoverageRepository
from app.services.escalation_repository import EscalationRepository
from app.services.conversation_repository import ConversationRepository
from app.services.post_call_summary_repository import PostCallSummaryRepository

SECONDS_PER_DAY = 86400
# A longer range is asked for in parts.
MAX_RANGE_DAYS = 366
# More calls than this in one report: the range is narrowed instead.
MAX_REPORT_CALLS = 20_000
# Daily points up to this many days, weekly beyond.
MAX_DAILY_BUCKETS = 62
MAX_THEMES = 5
MAX_THEME_CALLS = 5
# A quoted line is cut to this many characters.
MAX_QUOTE_CHARS = 300
# Two descriptions are about the same thing when they share at least
# THEME_MIN_SHARED_WORDS words (filler words and word endings aside), and
# those are this share of the shorter description's words.
THEME_SIMILARITY = 0.6
THEME_MIN_SHARED_WORDS = 2

Bucket = Literal["day", "week"]

_NOT_RAISED = ComplaintCoverageStatus.NOT_RAISED.value
_DETECTED = ComplaintCoverageStatus.DETECTED.value
_RESOLVED = ComplaintCoverageStatus.RESOLVED.value


class ReportError(ValueError):
    """A report that cannot be made as asked (the message says why)."""


@dataclass(frozen=True)
class ReportFilters:
    """Calls started in [started_from, started_to) (epoch seconds); every
    other filter is optional, and set ones must all match."""

    started_from: float
    started_to: float
    location_id: str | None = None
    executive_user_id: str | None = None
    direction: CallDirection | None = None
    # The call's overall tone, from its post-call summary.
    sentiment: SentimentLabel | None = None
    category: str | None = None

    def __post_init__(self) -> None:
        if self.started_to <= self.started_from:
            raise ReportError("The report's end date must be after its start date.")

    def require_reportable(self) -> None:
        """Raise when the range is longer than one report covers."""
        if self.started_to - self.started_from > MAX_RANGE_DAYS * SECONDS_PER_DAY:
            raise ReportError(f"A report covers at most {MAX_RANGE_DAYS} days.")


@dataclass(frozen=True)
class ReportComplaint:
    category: str
    # Where the complaint stands now (a ComplaintLifecycleStatus value), or
    # where the call left it when it is not tracked (ComplaintCoverageStatus).
    status: str
    # From the post-call summary; None while the call has none.
    description: str | None = None
    # Whether the executive asked the customer about it during the call.
    probed: bool = False
    # The customer's words: the first line of the call that raises it;
    # None when the call's lines carry no categories.
    quote: str | None = None
    # How sure the detector was (0 to 1); None when not recorded.
    confidence: float | None = None
    # Suggested questions about this complaint the executive accepted, and
    # skipped.
    questions_accepted: int = 0
    questions_skipped: int = 0


@dataclass(frozen=True)
class ReportCall:
    call_id: str
    start_time: float
    direction: CallDirection | None = None
    location_id: str | None = None
    location_name: str | None = None
    executive_user_id: str | None = None
    executive_name: str | None = None
    sentiment: SentimentLabel | None = None
    complaints: tuple[ReportComplaint, ...] = ()
    # Who the customer is, when known: the CRM's customer, else the
    # caller's number.
    customer_key: str | None = None
    # None: the call never escalated.
    escalation_level: EscalationLevel | None = None
    # Suggested questions the executive accepted, and skipped.
    questions_accepted: int = 0
    questions_skipped: int = 0
    # The call escalated and the escalation has not been resolved.
    escalation_open: bool = False
    # The customer's tone on the first and the last of their lines that
    # carry one; None for a call whose lines carry none.
    tone_start: SentimentLabel | None = None
    tone_end: SentimentLabel | None = None
    # Time the customer was kept on hold.
    hold_seconds: float = 0.0


# Tones from the mildest to the harshest.
TONE_SEVERITY = {
    SentimentLabel.POSITIVE: 0,
    SentimentLabel.NEUTRAL: 1,
    SentimentLabel.NEGATIVE: 2,
    SentimentLabel.FRUSTRATED: 3,
    SentimentLabel.ESCALATING: 4,
}


def tone_change(call: ReportCall) -> int | None:
    """Whether the customer's tone ended milder (-1) or harsher (1) than
    it began, or the same (0); None when the call's lines carry no tones."""
    if call.tone_start is None or call.tone_end is None:
        return None
    start, end = TONE_SEVERITY[call.tone_start], TONE_SEVERITY[call.tone_end]
    return (end > start) - (end < start)


def customer_key(customer_id: str | None, caller_number: str | None) -> str | None:
    if customer_id:
        return f"customer:{customer_id}"
    return f"number:{caller_number}" if caller_number else None


class ReportSource(ABC):
    @abstractmethod
    def calls(self, filters: ReportFilters, limit: int) -> tuple[ReportCall, ...]:
        """Up to `limit` calls matching every filter except the category
        (each with all its complaints), oldest first."""
        raise NotImplementedError

    def call(self, call_id: str) -> ReportCall | None:
        """That one call as reports see it; None when there is none (or
        the source cannot look a single call up)."""
        return None


class RenamingReportSource(ReportSource):
    """Another source's calls with each complaint under the name its
    category has now (current_name: stored name -> that name), so a
    renamed category keeps one line in every report. Two complaints of a
    call that come to the same name count once, as the first."""

    def __init__(self, source: ReportSource, current_name: Callable[[str], str]) -> None:
        self._source = source
        self._current_name = current_name

    def calls(self, filters: ReportFilters, limit: int) -> tuple[ReportCall, ...]:
        return tuple(self._renamed(call) for call in self._source.calls(filters, limit))

    def call(self, call_id: str) -> ReportCall | None:
        call = self._source.call(call_id)
        return None if call is None else self._renamed(call)

    def _renamed(self, call: ReportCall) -> ReportCall:
        names = [self._current_name(c.category) for c in call.complaints]
        if all(name == c.category for name, c in zip(names, call.complaints)):
            return call
        complaints: dict[str, ReportComplaint] = {}
        for name, complaint in zip(names, call.complaints):
            complaints.setdefault(name, replace(complaint, category=name))
        return replace(call, complaints=tuple(complaints.values()))


# ---- The report ----


@dataclass(frozen=True)
class CategoryTotal:
    category: str
    complaints: int
    # Of those, resolved by now.
    resolved: int


@dataclass(frozen=True)
class TrendSeries:
    category: str
    # One count per bucket of the report.
    counts: tuple[int, ...]


@dataclass(frozen=True)
class HeatmapLocation:
    # None: calls without a recorded location.
    location_id: str | None
    name: str


@dataclass(frozen=True)
class HeatmapRow:
    category: str
    # One count per location of the report.
    counts: tuple[int, ...]


@dataclass(frozen=True)
class Theme:
    """Complaints of one category described in similar words."""

    # The first of those descriptions.
    text: str
    # The customer's own words on one of those calls (the most recent that
    # has any); None when none of them has a line raising the category.
    quote: str | None
    complaints: int
    # Some of the calls, most recent first.
    call_ids: tuple[str, ...]


@dataclass(frozen=True)
class RootCause:
    category: str
    complaints: int
    resolved: int
    # Complaints no call summary describes (yet).
    undescribed: int
    themes: tuple[Theme, ...]


@dataclass(frozen=True)
class TonePoint:
    """One day or week of the tone trend."""

    # Calls with a tone, and those ending negative or worse.
    rated: int
    negative: int


@dataclass(frozen=True)
class ToneCount:
    label: SentimentLabel
    calls: int


@dataclass(frozen=True)
class ToneSummary:
    """How the calls of a report ended, and how they changed on the way."""

    # Calls with an overall tone (from their summary).
    rated_calls: int
    # Those calls by the tone they ended on, mildest first (every tone).
    by_tone: tuple[ToneCount, ...]
    negative_calls: int
    # Calls whose lines carry tones, and those whose customer ended in a
    # milder, or a harsher, tone than they began.
    tracked_calls: int
    improved_calls: int
    worsened_calls: int
    # One point per day or week of the report.
    trend: tuple[TonePoint, ...]


def report_buckets(
    filters: ReportFilters, bucket: Bucket | None, tz_offset_minutes: int
) -> tuple[Bucket, int, int, int]:
    """(bucket, the first and last bucket's index, the reader's clock
    ahead of UTC in seconds). bucket None: by day for a short range, by
    week for a long one."""
    days = (filters.started_to - filters.started_from) / SECONDS_PER_DAY
    bucket = bucket or ("day" if days <= MAX_DAILY_BUCKETS else "week")
    offset = tz_offset_minutes * 60
    first = _bucket_index(filters.started_from, bucket, offset)
    last = _bucket_index(filters.started_to - 1, bucket, offset)
    return bucket, first, last, offset


def tone_trend(
    calls: Iterable[ReportCall], bucket: Bucket, first: int, last: int, offset: int
) -> tuple[TonePoint, ...]:
    rated: Counter[int] = Counter()
    negative: Counter[int] = Counter()
    for call in calls:
        if call.sentiment is None:
            continue
        index = _bucket_index(call.start_time, bucket, offset) - first
        rated[index] += 1
        negative[index] += call.sentiment.is_negative
    return tuple(TonePoint(rated[i], negative[i]) for i in range(last - first + 1))


def tone_summary(
    calls: tuple[ReportCall, ...], bucket: Bucket, first: int, last: int, offset: int
) -> ToneSummary:
    ended = Counter(call.sentiment for call in calls if call.sentiment is not None)
    changes = [change for call in calls if (change := tone_change(call)) is not None]
    return ToneSummary(
        rated_calls=sum(ended.values()),
        by_tone=tuple(ToneCount(label, ended[label]) for label in TONE_SEVERITY),
        negative_calls=sum(count for label, count in ended.items() if label.is_negative),
        tracked_calls=len(changes),
        improved_calls=sum(1 for change in changes if change < 0),
        worsened_calls=sum(1 for change in changes if change > 0),
        trend=tone_trend(calls, bucket, first, last, offset),
    )


@dataclass(frozen=True)
class ComplaintRow:
    """One complaint with its call, as exports list them."""

    call_id: str
    start_time: float
    location_name: str | None
    executive_name: str | None
    direction: CallDirection | None
    sentiment: SentimentLabel | None
    category: str
    status: str
    description: str | None
    # The customer's words (see ReportComplaint.quote).
    quote: str | None = None


@dataclass(frozen=True)
class Report:
    filters: ReportFilters
    # What the filters' ids stand for, for headings.
    location_name: str | None
    executive_name: str | None
    bucket: Bucket
    tz_offset_minutes: int
    total_calls: int
    calls_with_complaints: int
    total_complaints: int
    # Most frequent first; the order of every per-category list below.
    categories: tuple[CategoryTotal, ...]
    # When each bucket starts (epoch seconds).
    bucket_starts: tuple[float, ...]
    trend: tuple[TrendSeries, ...]
    locations: tuple[HeatmapLocation, ...]
    heatmap: tuple[HeatmapRow, ...]
    root_causes: tuple[RootCause, ...]
    rows: tuple[ComplaintRow, ...]
    # How the calls ended, and the share ending negative per day or week.
    tone: ToneSummary


class ReportService:
    def __init__(
        self,
        source: ReportSource,
        locations: LocationRepository | None = None,
        users: UserRepository | None = None,
        max_calls: int = MAX_REPORT_CALLS,
    ) -> None:
        self._source = source
        self._locations = locations
        self._users = users
        self._max_calls = max_calls

    @property
    def source(self) -> ReportSource:
        return self._source

    def complaint_report(
        self,
        filters: ReportFilters,
        bucket: Bucket | None = None,
        tz_offset_minutes: int = 0,
    ) -> Report:
        """bucket None: by day for a short range, by week for a long one.
        tz_offset_minutes: the reader's clock ahead of UTC, so days and
        weeks start at their midnight."""
        filters.require_reportable()
        calls = self._source.calls(filters, self._max_calls + 1)
        if len(calls) > self._max_calls:
            raise ReportError(
                f"More than {self._max_calls:,} calls match. Choose a shorter date range "
                "or more filters."
            )
        if filters.category is not None:
            calls = tuple(
                replace(
                    call,
                    complaints=tuple(
                        c for c in call.complaints if c.category == filters.category
                    ),
                )
                for call in calls
                if any(c.category == filters.category for c in call.complaints)
            )

        bucket, first, last, offset = report_buckets(filters, bucket, tz_offset_minutes)

        totals: Counter[str] = Counter()
        resolved: Counter[str] = Counter()
        per_bucket: Counter[tuple[str, int]] = Counter()
        per_location: Counter[tuple[str, str | None]] = Counter()
        location_names: dict[str | None, str] = {}
        rows: list[ComplaintRow] = []
        for call in calls:
            index = _bucket_index(call.start_time, bucket, offset) - first
            if call.complaints:
                location_names[call.location_id] = call.location_name or "No location"
            for complaint in call.complaints:
                totals[complaint.category] += 1
                resolved[complaint.category] += complaint.status == _RESOLVED
                per_bucket[complaint.category, index] += 1
                per_location[complaint.category, call.location_id] += 1
                rows.append(
                    ComplaintRow(
                        call_id=call.call_id,
                        start_time=call.start_time,
                        location_name=call.location_name,
                        executive_name=call.executive_name,
                        direction=call.direction,
                        sentiment=call.sentiment,
                        category=complaint.category,
                        status=complaint.status,
                        description=complaint.description,
                        quote=complaint.quote,
                    )
                )

        categories = sorted(totals, key=lambda c: (-totals[c], c.casefold()))
        # Named locations by name, then the calls without one.
        location_ids = sorted(
            location_names,
            key=lambda i: (i is None, location_names[i].casefold()),
        )
        return Report(
            filters=filters,
            location_name=self._location_name(filters.location_id),
            executive_name=self._executive_name(filters.executive_user_id),
            bucket=bucket,
            tz_offset_minutes=tz_offset_minutes,
            total_calls=len(calls),
            calls_with_complaints=sum(1 for call in calls if call.complaints),
            total_complaints=sum(totals.values()),
            categories=tuple(CategoryTotal(c, totals[c], resolved[c]) for c in categories),
            bucket_starts=tuple(
                _bucket_start(index, bucket, offset) for index in range(first, last + 1)
            ),
            trend=tuple(
                TrendSeries(c, tuple(per_bucket[c, i] for i in range(last - first + 1)))
                for c in categories
            ),
            locations=tuple(HeatmapLocation(i, location_names[i]) for i in location_ids),
            heatmap=tuple(
                HeatmapRow(c, tuple(per_location[c, i] for i in location_ids))
                for c in categories
            ),
            root_causes=tuple(
                _root_cause(c, totals[c], resolved[c], [r for r in rows if r.category == c])
                for c in categories
            ),
            rows=tuple(rows),
            tone=tone_summary(calls, bucket, first, last, offset),
        )

    def _location_name(self, location_id: str | None) -> str | None:
        if location_id is None or self._locations is None:
            return None
        location = self._locations.get(location_id)
        return None if location is None else location.name

    def _executive_name(self, user_id: str | None) -> str | None:
        if user_id is None or self._users is None:
            return None
        user = self._users.get_by_id(user_id)
        return None if user is None else user.name


# ---- Days and weeks ----


def _bucket_index(at: float, bucket: Bucket, offset_seconds: int) -> int:
    """Which day (since 1970-01-01) or which Monday-to-Sunday week the
    moment falls in, by the reader's clock."""
    day = int((at + offset_seconds) // SECONDS_PER_DAY)
    # 1970-01-01 was a Thursday: three days after that week's Monday.
    return day if bucket == "day" else (day + 3) // 7


def _bucket_start(index: int, bucket: Bucket, offset_seconds: int) -> float:
    day = index if bucket == "day" else index * 7 - 3
    return float(day * SECONDS_PER_DAY - offset_seconds)


# ---- Root causes: descriptions in similar words ----

_FILLER_WORDS = frozenset(
    """a an and the of to in on at for from by with about into over after before is are was
    were be been being has have had do does did not no it its this that these those their
    his her they he she them customer customers caller complained complains complaint
    complaints said says stated reported mentioned also very still which who when while
    as but or if so than then there because due""".split()
)
_WORD = re.compile(r"[a-z0-9]+")
# What the rule-based summary writes in place of a description (see
# app.ai.summary.rule_based_provider): it says nothing about the complaint.
_PLACEHOLDER = re.compile(r"complaint identified during the call \(status: \w+\)\.?$")
_SUFFIXES = ("ing", "ed", "es", "s")


def _key_words(description: str) -> frozenset[str]:
    words = set()
    for word in _WORD.findall(description.casefold()):
        if word in _FILLER_WORDS:
            continue
        for suffix in _SUFFIXES:
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                word = word[: -len(suffix)]
                break
        # "estimate" and "estimated" are then the same word.
        if word.endswith("e") and len(word) > 4:
            word = word[:-1]
        words.add(word)
    return frozenset(words)


def _alike(a: frozenset[str], b: frozenset[str]) -> bool:
    shared = len(a & b)
    if shared < THEME_MIN_SHARED_WORDS:
        return False
    return shared / min(len(a), len(b)) >= THEME_SIMILARITY


def _what_it_says(row: ComplaintRow) -> str | None:
    """What the complaint is about: the call summary's description, or
    (when there is none, or it says nothing) the customer's own words."""
    description = (row.description or "").strip()
    if description and not _PLACEHOLDER.search(description):
        return description
    return row.quote or None


def first_quotes(lines: Iterable[tuple[str, Iterable[str] | None]]) -> dict[str, str]:
    """category -> the first line that raises it, from a call's lines in
    order, each as (words, the categories it raises)."""
    quotes: dict[str, str] = {}
    for words, categories in lines:
        for category in categories or ():
            if category not in quotes and words.strip():
                text = words.strip()
                quotes[category] = (
                    text if len(text) <= MAX_QUOTE_CHARS else text[: MAX_QUOTE_CHARS - 1] + "…"
                )
    return quotes


def _root_cause(
    category: str, complaints: int, resolved: int, rows: Iterable[ComplaintRow]
) -> RootCause:
    # Each group is known by the words of its first description.
    groups: list[tuple[frozenset[str], list[ComplaintRow]]] = []
    undescribed = 0
    for row in rows:
        text = _what_it_says(row)
        if text is None:
            undescribed += 1
            continue
        words = _key_words(text)
        for group_words, members in groups:
            if _alike(words, group_words):
                members.append(row)
                break
        else:
            groups.append((words, [row]))
    # Largest first; equal ones stay in the order they first came up.
    groups.sort(key=lambda group: -len(group[1]))
    return RootCause(
        category=category,
        complaints=complaints,
        resolved=resolved,
        undescribed=undescribed,
        themes=tuple(
            Theme(
                text=_what_it_says(members[0]),
                quote=next((m.quote for m in reversed(members) if m.quote), None),
                complaints=len(members),
                call_ids=tuple(
                    dict.fromkeys(m.call_id for m in reversed(members))
                )[:MAX_THEME_CALLS],
            )
            for _, members in groups[:MAX_THEMES]
        ),
    )


# ---- Calls from the in-memory stores (tests and local runs) ----


def call_complaints(
    coverage, summary, records=(), utterances=(), outcomes=()
) -> tuple[ReportComplaint, ...]:
    """A call's complaints: the categories raised on it, each described by
    the post-call summary when there is one, with the status of its
    tracked complaint (records) when it has one, the customer's words
    from the call's lines (utterances) when they carry categories, and
    what the executive did with the questions suggested about it
    (outcomes)."""
    quotes = first_quotes((u.transcript, u.complaint_categories) for u in utterances)
    accepted = Counter(o.target_category for o in outcomes if o.outcome.value == "accepted")
    skipped = Counter(o.target_category for o in outcomes if o.outcome.value == "skipped")
    descriptions = (
        {} if summary is None else {c.category: c.description for c in summary.complaints}
    )
    tracked = {record.category: record.status.value for record in records}
    if coverage is None:
        return ()
    return tuple(
        ReportComplaint(
            c.category,
            tracked.get(c.category, c.status.value),
            descriptions.get(c.category),
            probed=c.status.value != _DETECTED,
            quote=quotes.get(c.category),
            confidence=c.confidence,
            questions_accepted=accepted[c.category],
            questions_skipped=skipped[c.category],
        )
        for c in coverage.complaints
        if c.status.value != _NOT_RAISED
    )


class InMemoryReportSource(ReportSource):
    def __init__(
        self,
        conversations: ConversationRepository,
        coverages: ConversationCoverageRepository,
        summaries: PostCallSummaryRepository,
        locations: LocationRepository | None = None,
        users: UserRepository | None = None,
        complaints: ComplaintLifecycleRepository | None = None,
        call_customers: CallCustomerRepository | None = None,
        escalations: EscalationRepository | None = None,
        question_outcomes: QuestionOutcomeRepository | None = None,
    ) -> None:
        self._question_outcomes = question_outcomes
        self._complaints = complaints
        self._call_customers = call_customers
        self._escalations = escalations
        self._conversations = conversations
        self._coverages = coverages
        self._summaries = summaries
        self._locations = locations
        self._users = users

    def calls(self, filters: ReportFilters, limit: int) -> tuple[ReportCall, ...]:
        matching = []
        for conversation in self._conversations.list_page(self._conversations.count(), 0):
            if not filters.started_from <= conversation.start_time < filters.started_to:
                continue
            if filters.location_id not in (None, conversation.location_id):
                continue
            if filters.executive_user_id not in (None, conversation.executive_user_id):
                continue
            if filters.direction not in (None, conversation.direction):
                continue
            summary = self._summaries.get(conversation.call_id)
            sentiment = None if summary is None else summary.sentiment.label
            if filters.sentiment not in (None, sentiment):
                continue
            matching.append(self._report_call(conversation, summary))
        matching.sort(key=lambda call: (call.start_time, call.call_id))
        return tuple(matching[:limit])

    def call(self, call_id: str) -> ReportCall | None:
        conversation = self._conversations.get(call_id)
        if conversation is None:
            return None
        return self._report_call(conversation, self._summaries.get(call_id))

    def _report_call(self, conversation, summary) -> ReportCall:
        sentiment = None if summary is None else summary.sentiment.label
        location = (
            None
            if self._locations is None or conversation.location_id is None
            else self._locations.get(conversation.location_id)
        )
        executive = (
            None
            if self._users is None or conversation.executive_user_id is None
            else self._users.get_by_id(conversation.executive_user_id)
        )
        link = (
            None
            if self._call_customers is None
            else self._call_customers.get(conversation.call_id)
        )
        escalation = (
            None if self._escalations is None else self._escalations.get(conversation.call_id)
        )
        outcomes = (
            ()
            if self._question_outcomes is None
            else self._question_outcomes.list_for_calls([conversation.call_id]).get(
                conversation.call_id, ()
            )
        )
        accepted, skipped = count_outcomes(outcomes)
        tones = [u.sentiment for u in conversation.utterances if u.sentiment is not None]
        return (
            ReportCall(
                questions_accepted=accepted,
                questions_skipped=skipped,
                escalation_open=(
                    escalation is not None and escalation.status.value != "resolved"
                ),
                tone_start=tones[0] if tones else None,
                tone_end=tones[-1] if tones else None,
                hold_seconds=conversation.hold_seconds,
                customer_key=(
                    None if link is None else customer_key(link.customer_id, link.caller_number)
                ),
                escalation_level=None if escalation is None else escalation.level,
                call_id=conversation.call_id,
                start_time=conversation.start_time,
                direction=conversation.direction,
                location_id=conversation.location_id,
                location_name=None if location is None else location.name,
                executive_user_id=conversation.executive_user_id,
                executive_name=None if executive is None else executive.name,
                sentiment=sentiment,
                complaints=call_complaints(
                    self._coverages.get(conversation.call_id),
                    summary,
                    ()
                    if self._complaints is None
                    else self._complaints.list_for_call(conversation.call_id),
                    conversation.utterances,
                    outcomes,
                ),
            )
        )
