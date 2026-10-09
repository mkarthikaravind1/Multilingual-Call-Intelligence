import hashlib
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace

from app.ai.emerging_complaint.provider import (
    CallComplaintRecord,
    EmergingComplaintDiscoveryProvider,
    EmergingComplaintDiscoveryRequest,
)
from app.domain.conversation import ConversationStatus
from app.domain.emerging_complaint_candidate import (
    EmergingComplaintCandidate,
    EmergingComplaintReviewError,
    EmergingComplaintReviewStatus,
)
from app.services.call_service import CallService
from app.services.complaint_category_catalog import ComplaintCategoryCatalog
from app.services.conversation_coverage_repository import ConversationCoverageRepository
from app.services.emerging_complaint_repository import EmergingComplaintRepository
from app.services.live_state_store import LiveStateStore

logger = logging.getLogger(__name__)

# Discovery needs the theme to recur across calls.
MIN_CALLS_FOR_DISCOVERY = 2
# Quotes kept per candidate; the rule-based provider returns every match.
MAX_EVIDENCE_PER_CANDIDATE = 10
_PAGE_SIZE = 100
_LAST_RUN_KEY = "emerging_complaints:last_run"
# What the last run read; a background run over the same calls is skipped.
_FINGERPRINT_KEY = "emerging_complaints:last_fingerprint"
# Only one instance runs background discovery at a time.
_RUN_LOCK_NAME = "emerging_complaints:discovery"
_RUN_LOCK_TTL_SECONDS = 900.0


class EmergingComplaintNotFoundError(Exception):
    def __init__(self, candidate_id: str) -> None:
        super().__init__(f"No emerging complaint candidate {candidate_id!r}.")
        self.candidate_id = candidate_id


@dataclass(frozen=True)
class DiscoveryRun:
    ran_at: float
    calls_scanned: int
    candidates_found: int
    new_candidates: int
    # Why the provider was not asked (e.g. too few completed calls), if so.
    skipped_reason: str | None = None


class EmergingComplaintService:
    """Finds complaint themes that recur across completed calls but match no
    known category, stores them as candidates and lets supervisors review
    them.

    Discovery runs on demand (discover) or after calls complete
    (request_discovery), in the background and coalesced so a burst of
    completed calls causes at most one extra run.

    Background runs are kept cheap, which matters most with an LLM provider:
    they start at most once per min_interval_seconds (later requests wait
    and share one run), only one instance runs at a time, and a run whose
    calls are exactly those the previous run read is skipped without asking
    the provider. Manual runs always ask the provider.

    Accepting a candidate makes it a complaint category (see
    ComplaintCategoryCatalog); its name must not clash with another one.
    """

    def __init__(
        self,
        repository: EmergingComplaintRepository,
        provider: EmergingComplaintDiscoveryProvider,
        call_service: CallService,
        coverage_repository: ConversationCoverageRepository,
        max_calls: int = 200,
        executor: Executor | None = None,
        clock: Callable[[], float] = time.time,
        store: LiveStateStore | None = None,
        min_interval_seconds: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
        catalog: ComplaintCategoryCatalog | None = None,
    ) -> None:
        self._repository = repository
        self._catalog = catalog or ComplaintCategoryCatalog(repository)
        # Shares the last run with every instance; per-instance without it.
        self._live_state = store
        self._provider = provider
        self._call_service = call_service
        self._coverage_repository = coverage_repository
        self._max_calls = max_calls
        self._executor = executor
        self._clock = clock
        self._sleep = sleep
        self._min_interval_seconds = max(0.0, min_interval_seconds)
        self._last_fingerprint: str | None = None
        self._lock = threading.Lock()
        # Serialises discovery runs (manual and background).
        self._run_lock = threading.Lock()
        self._pending = False
        self._last_run: DiscoveryRun | None = None

    @property
    def last_run(self) -> DiscoveryRun | None:
        if self._live_state is not None:
            try:
                raw = self._live_state.get_json(_LAST_RUN_KEY)
                return None if raw is None else DiscoveryRun(**raw)
            except Exception:
                logger.exception("Could not read the last emerging-complaint discovery run")
        return self._last_run

    def _remember(self, run: DiscoveryRun, fingerprint: str) -> None:
        self._last_run = run
        self._last_fingerprint = fingerprint
        if self._live_state is not None:
            try:
                self._live_state.set_json(_LAST_RUN_KEY, asdict(run))
                self._live_state.set_json(_FINGERPRINT_KEY, fingerprint)
            except Exception:
                logger.exception("Could not share the emerging-complaint discovery run")

    def _stored_fingerprint(self) -> str | None:
        if self._live_state is not None:
            try:
                return self._live_state.get_json(_FINGERPRINT_KEY)
            except Exception:
                logger.exception("Could not read the last emerging-complaint discovery input")
        return self._last_fingerprint

    def _fingerprint(self, records: tuple[CallComplaintRecord, ...]) -> str:
        """Identifies what a run would read: which calls, how much was said
        in each, their complaint coverage, and which provider reads it."""
        digest = hashlib.sha256(type(self._provider).__name__.encode("utf-8"))
        for record in sorted(records, key=lambda r: r.call_id):
            complaints = sorted(
                (c.category, c.status.value) for c in record.complaint_coverages
            )
            digest.update(repr((record.call_id, len(record.utterances), complaints)).encode("utf-8"))
        return digest.hexdigest()

    def request_discovery(self) -> bool:
        """Schedule a background run unless one is already waiting. Returns
        whether a run was scheduled."""
        with self._lock:
            if self._pending:
                return False
            self._pending = True
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="emerging-complaints"
            )
        self._executor.submit(self._run_pending)
        return True

    def _run_pending(self) -> None:
        # Requests made while this waits are coalesced into this run.
        try:
            self._wait_for_min_interval()
        finally:
            with self._lock:
                self._pending = False
        try:
            self._discover_in_background()
        except Exception:
            logger.exception("Background emerging-complaint discovery failed")

    def _wait_for_min_interval(self) -> None:
        if not self._min_interval_seconds:
            return
        last = self.last_run
        if last is None:
            return
        delay = last.ran_at + self._min_interval_seconds - self._clock()
        if delay > 0:
            self._sleep(delay)

    def _discover_in_background(self) -> DiscoveryRun | None:
        token = None
        if self._live_state is not None:
            try:
                token = self._live_state.acquire_lock(_RUN_LOCK_NAME, _RUN_LOCK_TTL_SECONDS)
            except Exception:
                logger.exception("Could not take the emerging-complaint discovery lock")
                token = ""  # run anyway; this instance's own lock still applies
            if token is None:
                logger.info("Emerging-complaint discovery is running on another instance")
                return None
        try:
            return self._discover(skip_if_unchanged=True)
        finally:
            if token:
                try:
                    self._live_state.release_lock(_RUN_LOCK_NAME, token)
                except Exception:
                    logger.exception("Could not release the emerging-complaint discovery lock")

    def discover(self) -> DiscoveryRun:
        """Run discovery now (a person asked for it), even over unchanged calls."""
        # Never None: only background runs skip unchanged calls.
        return self._discover(skip_if_unchanged=False)  # type: ignore[return-value]

    def _discover(self, skip_if_unchanged: bool) -> DiscoveryRun | None:
        with self._run_lock:
            records = self._recent_completed_calls()
            fingerprint = self._fingerprint(records)
            if skip_if_unchanged and fingerprint == self._stored_fingerprint():
                logger.debug("Emerging-complaint discovery skipped: no new completed calls")
                return None
            now = self._clock()
            if len(records) < MIN_CALLS_FOR_DISCOVERY:
                run = DiscoveryRun(
                    ran_at=now,
                    calls_scanned=len(records),
                    candidates_found=0,
                    new_candidates=0,
                    skipped_reason=(
                        f"At least {MIN_CALLS_FOR_DISCOVERY} completed calls with "
                        "speech are needed."
                    ),
                )
                self._remember(run, fingerprint)
                return run

            discovered = self._provider.discover(
                EmergingComplaintDiscoveryRequest(
                    call_records=records,
                    known_categories=tuple(c.name for c in self._catalog.custom()),
                )
            )
            new_count = 0
            for candidate in discovered:
                if self._store(candidate, now):
                    new_count += 1

            run = DiscoveryRun(
                ran_at=now,
                calls_scanned=len(records),
                candidates_found=len(discovered),
                new_candidates=new_count,
            )
            self._remember(run, fingerprint)
            if new_count:
                logger.info("Emerging-complaint discovery found %d new theme(s)", new_count)
            return run

    def list_candidates(
        self, status: EmergingComplaintReviewStatus | None = None
    ) -> tuple[EmergingComplaintCandidate, ...]:
        """Most widespread first, then the most recently seen."""
        statuses = tuple(EmergingComplaintReviewStatus) if status is None else (status,)
        return tuple(
            sorted(
                self._repository.list_by_status(statuses),
                key=lambda c: (-len(c.call_ids), -c.occurrence_count, -c.last_seen_at),
            )
        )

    def review(
        self,
        candidate_id: str,
        decision: EmergingComplaintReviewStatus,
        by: str,
        note: str | None = None,
        category_name: str | None = None,
        category_description: str | None = None,
    ) -> EmergingComplaintCandidate:
        """Accepting names the category (default: the proposed name);
        rejecting or reopening an accepted theme stops it being detected."""
        with self._lock:
            candidate = self._repository.get(candidate_id)
            if candidate is None:
                raise EmergingComplaintNotFoundError(candidate_id)
            reviewed = candidate.review(
                decision, by, self._clock(), note, category_name, category_description
            )
            if decision is EmergingComplaintReviewStatus.ACCEPTED:
                clash = self._catalog.conflicting_name(reviewed.category_name, candidate_id)
                if clash is not None:
                    raise EmergingComplaintReviewError(
                        f"There is already a category called {clash!r}; choose another name."
                    )
            self._repository.save(reviewed)
        # Only this instance refreshes at once; others within the cache time.
        self._catalog.invalidate()
        if decision is EmergingComplaintReviewStatus.ACCEPTED:
            logger.info(
                "Emerging theme %s accepted as complaint category %r",
                candidate_id,
                reviewed.category_name,
            )
        return reviewed

    def _store(self, discovered: EmergingComplaintCandidate, at: float) -> bool:
        discovered = _trim_evidence(discovered)
        with self._lock:
            existing = self._repository.get(discovered.candidate_id)
            if existing is None:
                self._repository.save(discovered.first_stored(at))
                return True
            # A rejected theme stays rejected; its numbers still refresh.
            self._repository.save(existing.refreshed_from(discovered, at))
            return False

    def _recent_completed_calls(self) -> tuple[CallComplaintRecord, ...]:
        records: list[CallComplaintRecord] = []
        offset = 0
        while len(records) < self._max_calls:
            page = self._call_service.list_calls(_PAGE_SIZE, offset)
            if not page:
                break
            offset += len(page)
            for conversation in page:
                if (
                    conversation.status is not ConversationStatus.COMPLETED
                    or conversation.utterance_count == 0
                ):
                    continue
                coverage = self._coverage_repository.get(conversation.call_id)
                records.append(
                    CallComplaintRecord(
                        call_id=conversation.call_id,
                        utterances=conversation.utterances,
                        complaint_coverages=() if coverage is None else coverage.complaints,
                    )
                )
                if len(records) >= self._max_calls:
                    break
        return tuple(records)


def _trim_evidence(candidate: EmergingComplaintCandidate) -> EmergingComplaintCandidate:
    if len(candidate.evidence) <= MAX_EVIDENCE_PER_CANDIDATE:
        return candidate
    return replace(candidate, evidence=candidate.evidence[:MAX_EVIDENCE_PER_CANDIDATE])
