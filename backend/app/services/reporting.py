"""Complaint reports for supervisors: how often each category comes up over
time and per location, and what the complaints in a category are about.

Everything is counted from what calls already store (their complaint
categories, post-call summary, location and executive). Nothing here asks
an AI model: the "root causes" are complaint descriptions grouped by
similar wording, by a fixed rule.
"""

import re
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Literal

from app.ai.sentiment.provider import SentimentLabel
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.complaint_lifecycle_repository import ComplaintLifecycleRepository
from app.domain.conversation import CallDirection
from app.domain.location import LocationRepository
from app.domain.user_repository import UserRepository
from app.services.conversation_coverage_repository import ConversationCoverageRepository
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
# Two descriptions are about the same thing when they share at least
# THEME_MIN_SHARED_WORDS words (filler words and word endings aside), and
# those are this share of the shorter description's words.
THEME_SIMILARITY = 0.6
THEME_MIN_SHARED_WORDS = 2

Bucket = Literal["day", "week"]

_NOT_RAISED = ComplaintCoverageStatus.NOT_RAISED.value
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


class ReportSource(ABC):
    @abstractmethod
    def calls(self, filters: ReportFilters, limit: int) -> tuple[ReportCall, ...]:
        """Up to `limit` calls matching every filter except the category
        (each with all its complaints), oldest first."""
        raise NotImplementedError


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

    def complaint_report(
        self,
        filters: ReportFilters,
        bucket: Bucket | None = None,
        tz_offset_minutes: int = 0,
    ) -> Report:
        """bucket None: by day for a short range, by week for a long one.
        tz_offset_minutes: the reader's clock ahead of UTC, so days and
        weeks start at their midnight."""
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

        days = (filters.started_to - filters.started_from) / SECONDS_PER_DAY
        bucket = bucket or ("day" if days <= MAX_DAILY_BUCKETS else "week")
        offset = tz_offset_minutes * 60
        first = _bucket_index(filters.started_from, bucket, offset)
        last = _bucket_index(filters.started_to - 1, bucket, offset)

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


def _root_cause(
    category: str, complaints: int, resolved: int, rows: Iterable[ComplaintRow]
) -> RootCause:
    # Each group is known by the words of its first description.
    groups: list[tuple[frozenset[str], list[ComplaintRow]]] = []
    undescribed = 0
    for row in rows:
        if not row.description or not row.description.strip() or _PLACEHOLDER.search(
            row.description.strip()
        ):
            undescribed += 1
            continue
        words = _key_words(row.description)
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
                text=members[0].description.strip(),
                complaints=len(members),
                call_ids=tuple(
                    dict.fromkeys(m.call_id for m in reversed(members))
                )[:MAX_THEME_CALLS],
            )
            for _, members in groups[:MAX_THEMES]
        ),
    )


# ---- Calls from the in-memory stores (tests and local runs) ----


def call_complaints(coverage, summary, records=()) -> tuple[ReportComplaint, ...]:
    """A call's complaints: the categories raised on it, each described by
    the post-call summary when there is one, with the status of its
    tracked complaint (records) when it has one."""
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
    ) -> None:
        self._complaints = complaints
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
            matching.append(
                ReportCall(
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
                    ),
                )
            )
        matching.sort(key=lambda call: (call.start_time, call.call_id))
        return tuple(matching[:limit])
