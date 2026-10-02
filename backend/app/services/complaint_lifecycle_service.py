import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.complaint_lifecycle import (
    CLOSED_STATUSES,
    MANUAL_STATUSES,
    ComplaintLifecycleEvent,
    ComplaintLifecycleRecord,
    ComplaintLifecycleStatus,
)
from app.domain.complaint_lifecycle_repository import ComplaintLifecycleRepository
from app.domain.conversation_coverage import ConversationCoverage

SYSTEM_ACTOR = "system"

# ComplaintCoverageStatus -> ComplaintLifecycleStatus. NOT_RAISED has no
# lifecycle equivalent, so it is intentionally omitted.
_COVERAGE_TO_LIFECYCLE: dict[ComplaintCoverageStatus, ComplaintLifecycleStatus] = {
    ComplaintCoverageStatus.DETECTED: ComplaintLifecycleStatus.DETECTED,
    ComplaintCoverageStatus.PROBED: ComplaintLifecycleStatus.PROBED,
    ComplaintCoverageStatus.COVERED: ComplaintLifecycleStatus.COVERED,
    ComplaintCoverageStatus.RESOLVED: ComplaintLifecycleStatus.RESOLVED,
    ComplaintCoverageStatus.UNRESOLVED: ComplaintLifecycleStatus.UNRESOLVED,
}

# The order call analysis moves a complaint in while the call runs.
_IN_CALL_ORDER = (
    ComplaintLifecycleStatus.DETECTED,
    ComplaintLifecycleStatus.PROBED,
    ComplaintLifecycleStatus.COVERED,
)

_OPEN_STATUSES = tuple(s for s in ComplaintLifecycleStatus if s not in CLOSED_STATUSES)

# The stages the complaints page filters by, as the complaint's current status.
COMPLAINT_STAGES: dict[str, frozenset[ComplaintLifecycleStatus]] = {
    # RAISED is the moment before detection; people see it as detected.
    "detected": frozenset({ComplaintLifecycleStatus.RAISED, ComplaintLifecycleStatus.DETECTED}),
    "probed": frozenset({ComplaintLifecycleStatus.PROBED}),
    "covered": frozenset({ComplaintLifecycleStatus.COVERED}),
    "outcome": frozenset({ComplaintLifecycleStatus.RESOLVED, ComplaintLifecycleStatus.UNRESOLVED}),
    "follow_up": frozenset({ComplaintLifecycleStatus.FOLLOW_UP}),
}

CALL_ENDED_NOTE = "The call ended before this complaint was resolved; it needs a follow-up."


def complaint_id_for(call_id: str, category: str) -> str:
    return f"{call_id}:{category}"


class ComplaintLifecycleNotFoundError(Exception):
    def __init__(self, complaint_id: str) -> None:
        super().__init__(f"No complaint lifecycle record found for complaint_id={complaint_id!r}.")
        self.complaint_id = complaint_id


class ComplaintLifecycleCallMismatchError(Exception):
    def __init__(self, complaint_id: str, expected_call_id: str, actual_call_id: str) -> None:
        super().__init__(
            f"complaint_id={complaint_id!r} belongs to call_id={actual_call_id!r}, "
            f"not the expected call_id={expected_call_id!r}."
        )
        self.complaint_id = complaint_id
        self.expected_call_id = expected_call_id
        self.actual_call_id = actual_call_id


class ComplaintActionError(Exception):
    """A person asked for a status change that is not allowed now."""


@dataclass(frozen=True)
class ComplaintView:
    record: ComplaintLifecycleRecord
    events: tuple[ComplaintLifecycleEvent, ...] = ()


class ComplaintLifecycleService:
    """Tracks each complaint raised on a call from detection to closure.

    Call analysis drives the in-call statuses (sync_from_coverage); when the
    call ends, complaints still open are flagged for follow-up (close_call);
    after that people resolve them or schedule follow-ups (apply_action).
    Every change is recorded as an event. Transition rules live on the
    domain model.
    """

    def __init__(
        self,
        repository: ComplaintLifecycleRepository,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._repository = repository
        self._clock = clock
        # Serialises the read-modify-write of a complaint.
        self._lock = threading.RLock()

    # --- Low-level operations -------------------------------------------

    def create(
        self,
        complaint_id: str,
        call_id: str,
        category: str,
        first_detected_at: float,
        status: ComplaintLifecycleStatus = ComplaintLifecycleStatus.RAISED,
        follow_up_required: bool = False,
        customer_id: str | None = None,
        actor: str = SYSTEM_ACTOR,
        note: str | None = None,
    ) -> ComplaintLifecycleRecord:
        record = ComplaintLifecycleRecord(
            complaint_id=complaint_id,
            call_id=call_id,
            category=category,
            status=status,
            first_detected_at=first_detected_at,
            last_updated_at=first_detected_at,
            follow_up_required=follow_up_required,
            customer_id=customer_id,
        )
        self._repository.save(record)
        self._record_event(record, actor, note)
        return record

    def get(self, complaint_id: str) -> ComplaintLifecycleRecord:
        record = self._repository.get(complaint_id)
        if record is None:
            raise ComplaintLifecycleNotFoundError(complaint_id)
        return record

    def transition(
        self,
        complaint_id: str,
        call_id: str,
        new_status: ComplaintLifecycleStatus,
        at: float,
        follow_up_required: bool | None = None,
        actor: str = SYSTEM_ACTOR,
        note: str | None = None,
    ) -> ComplaintLifecycleRecord:
        with self._lock:
            record = self.get(complaint_id)
            if record.call_id != call_id:
                raise ComplaintLifecycleCallMismatchError(complaint_id, call_id, record.call_id)

            updated = record.transition_to(
                new_status, at=at, follow_up_required=follow_up_required
            )
            self._repository.save(updated)
            self._record_event(updated, actor, note)
            return updated

    # --- Driven by the call ---------------------------------------------

    def sync_from_coverage(
        self,
        coverage: ConversationCoverage,
        at: float | None = None,
        customer_id: str | None = None,
    ) -> tuple[ComplaintLifecycleRecord, ...]:
        """Bring the call's complaint records up to its current coverage.

        Only moves forward: a complaint a person has already closed or
        handed to follow-up is left alone.
        """
        if at is None:
            at = self._clock()
        with self._lock:
            for complaint in coverage.complaints:
                target = _COVERAGE_TO_LIFECYCLE.get(complaint.status)
                if target is None:
                    continue

                complaint_id = complaint_id_for(coverage.call_id, complaint.category)
                record = self._repository.get(complaint_id)
                if record is None:
                    self.create(
                        complaint_id=complaint_id,
                        call_id=coverage.call_id,
                        category=complaint.category,
                        first_detected_at=at,
                        status=target,
                        customer_id=customer_id,
                    )
                    continue

                step_at = max(at, record.last_updated_at)
                for step in _steps_to(record.status, target):
                    record = self.transition(
                        complaint_id=complaint_id,
                        call_id=coverage.call_id,
                        new_status=step,
                        at=step_at,
                    )
            return self._repository.list_for_call(coverage.call_id)

    def close_call(
        self, call_id: str, customer_id: str | None = None
    ) -> tuple[ComplaintLifecycleRecord, ...]:
        """Called once the call has ended: link the customer and flag every
        complaint the call left unresolved for follow-up."""
        with self._lock:
            now = self._clock()
            for record in self._repository.list_for_call(call_id):
                changes: dict = {}
                if customer_id is not None and record.customer_id is None:
                    changes["customer_id"] = customer_id
                needs_follow_up = record.is_open and not record.follow_up_required
                if needs_follow_up:
                    changes["follow_up_required"] = True
                if not changes:
                    continue
                updated = record.with_changes(max(now, record.last_updated_at), **changes)
                self._repository.save(updated)
                if needs_follow_up:
                    self._record_event(updated, SYSTEM_ACTOR, CALL_ENDED_NOTE)
            return self._repository.list_for_call(call_id)

    def attach_customer(self, call_id: str, customer_id: str) -> None:
        """Link the call's complaints to a customer identified later on."""
        with self._lock:
            for record in self._repository.list_for_call(call_id):
                if record.customer_id is None:
                    self._repository.save(
                        record.with_changes(record.last_updated_at, customer_id=customer_id)
                    )

    # --- Worked by people -------------------------------------------------

    def apply_action(
        self,
        complaint_id: str,
        new_status: ComplaintLifecycleStatus,
        actor: str,
        note: str | None = None,
    ) -> ComplaintView:
        if new_status not in MANUAL_STATUSES:
            raise ComplaintActionError(
                f"{new_status.value!r} is set by call analysis and cannot be chosen by hand."
            )
        note = note.strip() if note and note.strip() else None
        with self._lock:
            record = self.get(complaint_id)
            if new_status not in record.allowed_actions():
                raise ComplaintActionError(
                    f"A {record.status.value!r} complaint cannot be marked {new_status.value!r}."
                )
            self.transition(
                complaint_id,
                record.call_id,
                new_status,
                at=max(self._clock(), record.last_updated_at),
                # Scheduling a follow-up raises the flag; resolving clears it.
                follow_up_required=(
                    True
                    if new_status is ComplaintLifecycleStatus.FOLLOW_UP
                    else False
                    if new_status is ComplaintLifecycleStatus.RESOLVED
                    else None
                ),
                actor=actor,
                note=note,
            )
            return self.get_view(complaint_id)

    # --- Reads ---------------------------------------------------------------

    def get_view(self, complaint_id: str) -> ComplaintView:
        return self._with_events((self.get(complaint_id),))[0]

    def list_for_call(self, call_id: str) -> tuple[ComplaintView, ...]:
        return self._with_events(self._repository.list_for_call(call_id))

    def customer_history(
        self, customer_id: str, exclude_call_id: str | None = None
    ) -> tuple[ComplaintView, ...]:
        """The customer's complaints on other calls, most recent first."""
        records = [
            r
            for r in self._repository.list_for_customer(customer_id)
            if r.call_id != exclude_call_id
        ]
        records.sort(key=lambda r: r.first_detected_at, reverse=True)
        return self._with_events(tuple(records))

    def list_queue(
        self,
        state: str = "open",
        limit: int = 200,
        categories: Iterable[str] = (),
        stages: Iterable[str] = (),
    ) -> tuple[ComplaintView, ...]:
        """"open": complaints needing attention, follow-ups first, then the
        oldest first. "resolved": most recently closed first. "all": newest
        first. Non-empty categories / stages (keys of COMPLAINT_STAGES) keep
        only complaints in one of them; the limit applies after filtering."""
        if state == "open":
            records = sorted(
                self._repository.list_by_status(_OPEN_STATUSES),
                key=lambda r: (not r.follow_up_required, r.first_detected_at),
            )
        elif state == "resolved":
            records = sorted(
                self._repository.list_by_status(CLOSED_STATUSES),
                key=lambda r: r.last_updated_at,
                reverse=True,
            )
        elif state == "all":
            records = sorted(
                self._repository.list_by_status(ComplaintLifecycleStatus),
                key=lambda r: r.first_detected_at,
                reverse=True,
            )
        else:
            raise ValueError(f"Unknown complaint queue state: {state!r}.")
        wanted_categories = set(categories)
        wanted_statuses = {status for stage in stages for status in COMPLAINT_STAGES[stage]}
        records = [
            r
            for r in records
            if (not wanted_categories or r.category in wanted_categories)
            and (not wanted_statuses or r.status in wanted_statuses)
        ]
        return self._with_events(tuple(records[:limit]))

    def _with_events(
        self, records: tuple[ComplaintLifecycleRecord, ...]
    ) -> tuple[ComplaintView, ...]:
        events = self._repository.list_events(r.complaint_id for r in records)
        return tuple(ComplaintView(r, events.get(r.complaint_id, ())) for r in records)

    def _record_event(
        self, record: ComplaintLifecycleRecord, actor: str, note: str | None
    ) -> None:
        self._repository.add_event(
            ComplaintLifecycleEvent(
                complaint_id=record.complaint_id,
                status=record.status,
                at=record.last_updated_at,
                actor=actor,
                note=note,
            )
        )


def _steps_to(
    current: ComplaintLifecycleStatus, target: ComplaintLifecycleStatus
) -> list[ComplaintLifecycleStatus]:
    """In-call steps from current to target; none when the call has nothing
    new to say (already there, already past it, or handled by a person)."""
    if current == target or current not in _IN_CALL_ORDER:
        return []

    path: list[ComplaintLifecycleStatus] = list(_IN_CALL_ORDER)
    if target in (ComplaintLifecycleStatus.RESOLVED, ComplaintLifecycleStatus.UNRESOLVED):
        path.append(target)
    if target not in path:
        return []

    start = path.index(current) + 1
    return path[start : path.index(target) + 1]
