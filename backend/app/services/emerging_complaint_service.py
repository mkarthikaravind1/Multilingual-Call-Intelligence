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
    EmergingComplaintReviewStatus,
)
from app.services.call_service import CallService
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
    ) -> None:
        self._repository = repository
        # Shares the last run with every instance; per-instance without it.
        self._live_state = store
        self._provider = provider
        self._call_service = call_service
        self._coverage_repository = coverage_repository
        self._max_calls = max_calls
        self._executor = executor
        self._clock = clock
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

    def _remember(self, run: DiscoveryRun) -> None:
        self._last_run = run
        if self._live_state is not None:
            try:
                self._live_state.set_json(_LAST_RUN_KEY, asdict(run))
            except Exception:
                logger.exception("Could not share the emerging-complaint discovery run")

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
        with self._lock:
            self._pending = False
        try:
            self.discover()
        except Exception:
            logger.exception("Background emerging-complaint discovery failed")

    def discover(self) -> DiscoveryRun:
        with self._run_lock:
            records = self._recent_completed_calls()
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
                self._remember(run)
                return run

            discovered = self._provider.discover(
                EmergingComplaintDiscoveryRequest(call_records=records)
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
            self._remember(run)
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
    ) -> EmergingComplaintCandidate:
        with self._lock:
            candidate = self._repository.get(candidate_id)
            if candidate is None:
                raise EmergingComplaintNotFoundError(candidate_id)
            reviewed = candidate.review(decision, by, self._clock(), note)
            self._repository.save(reviewed)
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
