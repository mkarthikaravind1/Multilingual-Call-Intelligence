import threading
from abc import ABC, abstractmethod
from collections.abc import Iterable

from app.domain.complaint_lifecycle import (
    ComplaintLifecycleEvent,
    ComplaintLifecycleRecord,
    ComplaintLifecycleStatus,
)


class ComplaintLifecycleRepository(ABC):
    @abstractmethod
    def save(self, record: ComplaintLifecycleRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, complaint_id: str) -> ComplaintLifecycleRecord | None:
        raise NotImplementedError

    @abstractmethod
    def list_for_call(self, call_id: str) -> tuple[ComplaintLifecycleRecord, ...]:
        """The call's complaints, first detected first."""
        raise NotImplementedError

    @abstractmethod
    def list_for_customer(self, customer_id: str) -> tuple[ComplaintLifecycleRecord, ...]:
        """All of the customer's complaints, first detected first."""
        raise NotImplementedError

    @abstractmethod
    def list_by_status(
        self, statuses: Iterable[ComplaintLifecycleStatus]
    ) -> tuple[ComplaintLifecycleRecord, ...]:
        raise NotImplementedError

    @abstractmethod
    def add_event(self, event: ComplaintLifecycleEvent) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_events(
        self, complaint_ids: Iterable[str]
    ) -> dict[str, tuple[ComplaintLifecycleEvent, ...]]:
        """Each complaint's history, oldest first. Complaints without events
        are left out."""
        raise NotImplementedError


class InMemoryComplaintLifecycleRepository(ComplaintLifecycleRepository):
    def __init__(self) -> None:
        self._records: dict[str, ComplaintLifecycleRecord] = {}
        self._events: dict[str, list[ComplaintLifecycleEvent]] = {}
        self._lock = threading.Lock()

    def save(self, record: ComplaintLifecycleRecord) -> None:
        with self._lock:
            self._records[record.complaint_id] = record

    def get(self, complaint_id: str) -> ComplaintLifecycleRecord | None:
        return self._records.get(complaint_id)

    def list_for_call(self, call_id: str) -> tuple[ComplaintLifecycleRecord, ...]:
        return self._sorted(r for r in self._records.values() if r.call_id == call_id)

    def list_for_customer(self, customer_id: str) -> tuple[ComplaintLifecycleRecord, ...]:
        return self._sorted(r for r in self._records.values() if r.customer_id == customer_id)

    def list_by_status(
        self, statuses: Iterable[ComplaintLifecycleStatus]
    ) -> tuple[ComplaintLifecycleRecord, ...]:
        wanted = set(statuses)
        return self._sorted(r for r in self._records.values() if r.status in wanted)

    def add_event(self, event: ComplaintLifecycleEvent) -> None:
        with self._lock:
            self._events.setdefault(event.complaint_id, []).append(event)

    def list_events(
        self, complaint_ids: Iterable[str]
    ) -> dict[str, tuple[ComplaintLifecycleEvent, ...]]:
        return {
            complaint_id: tuple(self._events[complaint_id])
            for complaint_id in complaint_ids
            if complaint_id in self._events
        }

    @staticmethod
    def _sorted(
        records: Iterable[ComplaintLifecycleRecord],
    ) -> tuple[ComplaintLifecycleRecord, ...]:
        return tuple(sorted(records, key=lambda r: (r.first_detected_at, r.complaint_id)))
