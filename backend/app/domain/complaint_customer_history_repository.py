from abc import ABC, abstractmethod

from app.domain.complaint_lifecycle import ComplaintLifecycleRecord, ComplaintLifecycleStatus

# RESOLVED is the only fully closed status; FOLLOW_UP (reachable from
# either RESOLVED or UNRESOLVED) still needs attention, so it counts
# as active.
_CLOSED_STATUSES = frozenset({ComplaintLifecycleStatus.RESOLVED})


class ComplaintCustomerHistoryRepository(ABC):
    @abstractmethod
    def save(self, record: ComplaintLifecycleRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, complaint_id: str) -> ComplaintLifecycleRecord | None:
        raise NotImplementedError

    @abstractmethod
    def get_active_for_customer(self, customer_id: str) -> tuple[ComplaintLifecycleRecord, ...]:
        raise NotImplementedError

    @abstractmethod
    def get_history_for_customer(self, customer_id: str) -> tuple[ComplaintLifecycleRecord, ...]:
        raise NotImplementedError


class InMemoryComplaintCustomerHistoryRepository(ComplaintCustomerHistoryRepository):
    def __init__(self) -> None:
        self._records: dict[str, ComplaintLifecycleRecord] = {}

    def save(self, record: ComplaintLifecycleRecord) -> None:
        self._records[record.complaint_id] = record

    def get(self, complaint_id: str) -> ComplaintLifecycleRecord | None:
        return self._records.get(complaint_id)

    def get_active_for_customer(self, customer_id: str) -> tuple[ComplaintLifecycleRecord, ...]:
        return tuple(
            sorted(
                (
                    record
                    for record in self._records.values()
                    if record.customer_id == customer_id and record.status not in _CLOSED_STATUSES
                ),
                key=lambda record: record.first_detected_at,
            )
        )

    def get_history_for_customer(self, customer_id: str) -> tuple[ComplaintLifecycleRecord, ...]:
        return tuple(
            sorted(
                (record for record in self._records.values() if record.customer_id == customer_id),
                key=lambda record: record.first_detected_at,
            )
        )