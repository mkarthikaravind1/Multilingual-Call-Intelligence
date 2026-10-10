"""The supervisor's live view: every call in progress with where it stands.

Built to be read every few seconds by several supervisors while hundreds of
calls are in progress:

- the number of reads does not grow with the number of calls: one for the
  calls, and one each for their complaints, tones and alerts;
- transcripts are never loaded;
- nothing is written: the alerts are kept up to date by LiveAlertSweeper
  (a background job) and by each call's own analysis;
- the assembled view is shared for a moment, so many open pages cost the
  same as one;
- filtering, ordering and paging happen here, so a page holds 50 calls
  however many there are.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.domain.call_alert import CallAlert
from app.domain.complaint_coverage import ComplaintCoverage, ComplaintCoverageStatus
from app.domain.escalation import EscalationLevel, EscalationStatus
from app.domain.sentiment import SentimentLabel
from app.services.call_alerts import CallAlertService
from app.services.call_listing import CallListingQuery, CallListItem
from app.services.conversation_coverage_repository import ConversationCoverageRepository
from app.services.live_analysis_store import LiveAnalysisStore
from app.services.live_state_store import LiveStateStore

logger = logging.getLogger(__name__)

# Far above the calls one centre has in progress; bounds a single read.
MAX_LIVE_CALLS = 2000
DEFAULT_CACHE_SECONDS = 2.0
_SWEEP_LOCK = "live_alert_sweep"


@dataclass(frozen=True)
class LiveCall:
    call: CallListItem
    # The customer's tone at the latest analysis; None before the first.
    sentiment: SentimentLabel | None
    # The complaints raised so far.
    complaints: tuple[ComplaintCoverage, ...]
    # Standing alerts only.
    alerts: tuple[CallAlert, ...]

    @property
    def escalated(self) -> bool:
        level = self.call.escalation_level
        return (
            level is not None
            and level is not EscalationLevel.NONE
            and self.call.escalation_status is not EscalationStatus.RESOLVED
        )


@dataclass(frozen=True)
class LiveCallFilters:
    """Every filter is optional; set ones must all match."""

    location_id: str | None = None
    executive_user_id: str | None = None
    sentiment: SentimentLabel | None = None
    alerts_only: bool = False

    def match(self, live: LiveCall) -> bool:
        if self.location_id is not None and live.call.location_id != self.location_id:
            return False
        if (
            self.executive_user_id is not None
            and live.call.executive_user_id != self.executive_user_id
        ):
            return False
        if self.sentiment is not None and live.sentiment is not self.sentiment:
            return False
        return not self.alerts_only or bool(live.alerts)


@dataclass(frozen=True)
class LiveCallsPage:
    # One page of the calls matching the filters, most urgent first.
    items: tuple[LiveCall, ...]
    # Calls matching the filters, across all pages.
    matching: int
    # Over every call in progress, whatever the filters:
    total: int
    with_alerts: int
    negative_tone: int
    escalated: int
    # The server's clock (epoch seconds), for showing durations.
    now: float


class LiveCallsBoard:
    def __init__(
        self,
        listing: CallListingQuery,
        coverage_repository: ConversationCoverageRepository,
        live_analysis: LiveAnalysisStore,
        alert_service: CallAlertService | None = None,
        cache_seconds: float = DEFAULT_CACHE_SECONDS,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._listing = listing
        self._coverage_repository = coverage_repository
        self._live_analysis = live_analysis
        self._alert_service = alert_service
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._cached: tuple[LiveCall, ...] | None = None
        self._cached_at = 0.0

    def page(self, filters: LiveCallFilters, limit: int, offset: int) -> LiveCallsPage:
        calls = self._calls()
        matching = [live for live in calls if filters.match(live)]
        return LiveCallsPage(
            items=tuple(matching[offset : offset + limit]),
            matching=len(matching),
            total=len(calls),
            with_alerts=sum(1 for live in calls if live.alerts),
            negative_tone=sum(
                1 for live in calls if live.sentiment is not None and live.sentiment.is_negative
            ),
            escalated=sum(1 for live in calls if live.escalated),
            now=self._clock(),
        )

    def _calls(self) -> tuple[LiveCall, ...]:
        """Every call in progress, most urgent first. Read at most once per
        cache_seconds: requests arriving meanwhile (or while a read is under
        way) share its result."""
        with self._lock:
            age = self._monotonic() - self._cached_at
            if self._cached is None or age >= self._cache_seconds:
                self._cached = self._read()
                self._cached_at = self._monotonic()
            return self._cached

    def _read(self) -> tuple[LiveCall, ...]:
        calls = self._listing.active_calls(MAX_LIVE_CALLS)
        ids = [call.call_id for call in calls]
        if not ids:
            return ()
        # The calls themselves are needed; a store beside them that cannot
        # be read leaves its part of each card empty.
        coverages = self._best_effort("complaints", self._coverage_repository.get_many, ids)
        analyses = self._live_analysis.load_many(ids)
        alerts = (
            {}
            if self._alert_service is None
            else self._best_effort("alerts", self._alert_service.list_for_calls, ids)
        )
        live_calls = []
        for call in calls:
            coverage = coverages.get(call.call_id)
            analysis = analyses.get(call.call_id)
            sentiment = None if analysis is None else analysis.sentiment
            live_calls.append(
                LiveCall(
                    call=call,
                    sentiment=None if sentiment is None else sentiment.label,
                    complaints=tuple(
                        complaint
                        for complaint in (() if coverage is None else coverage.complaints)
                        if complaint.status is not ComplaintCoverageStatus.NOT_RAISED
                    ),
                    alerts=tuple(a for a in alerts.get(call.call_id, ()) if a.is_open),
                )
            )
        live_calls.sort(key=_urgency)
        return tuple(live_calls)

    @staticmethod
    def _best_effort(what: str, read: Callable[[list[str]], dict], ids: list[str]) -> dict:
        try:
            return read(ids)
        except Exception:
            logger.exception("Could not read the %s of %d live calls", what, len(ids))
            return {}


def _urgency(live: LiveCall) -> tuple:
    """Calls with the most alerts first, then the most escalated, then the
    longest running."""
    level = live.call.escalation_level if live.escalated else None
    return (-len(live.alerts), -(0 if level is None else level.rank), live.call.start_time)


class LiveAlertSweeper:
    """Keeps the alerts of the calls in progress up to date (see
    CallAlertService.sweep), so reading the live view writes nothing. Run
    as a background job; with several API instances, one of them sweeps in
    each interval."""

    def __init__(
        self,
        listing: CallListingQuery,
        coverage_repository: ConversationCoverageRepository,
        alert_service: CallAlertService,
        live_analysis: LiveAnalysisStore,
        live_state: LiveStateStore,
        interval_seconds: float,
    ) -> None:
        self._listing = listing
        self._coverage_repository = coverage_repository
        self._alert_service = alert_service
        self._live_analysis = live_analysis
        self._live_state = live_state
        self._interval_seconds = interval_seconds

    def run(self) -> int:
        """Sweep once; returns how many calls' alerts changed."""
        # Not released: it runs out just before the next interval, so the
        # other instances find it taken until then.
        lock_seconds = max(1.0, self._interval_seconds - 1.0)
        if self._live_state.acquire_lock(_SWEEP_LOCK, lock_seconds) is None:
            return 0
        ids = [call.call_id for call in self._listing.active_calls(MAX_LIVE_CALLS)]
        if not ids:
            return 0
        changed = self._alert_service.sweep(ids, self._coverage_repository.get_many(ids))
        for call_id in changed:
            # The executive's own screen picks the change up.
            self._live_analysis.touch(call_id)
        return len(changed)
