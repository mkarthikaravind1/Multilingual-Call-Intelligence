from abc import ABC, abstractmethod

from app.domain.complaint_lifecycle import ComplaintLifecycleRecord


class ComplaintLifecycleRepository(ABC):
    @abstractmethod
    def save(self, record: ComplaintLifecycleRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, complaint_id: str) -> ComplaintLifecycleRecord | None:
        raise NotImplementedError


class InMemoryComplaintLifecycleRepository(ComplaintLifecycleRepository):
    def __init__(self) -> None:
        self._records: dict[str, ComplaintLifecycleRecord] = {}

    def save(self, record: ComplaintLifecycleRecord) -> None:
        self._records[record.complaint_id] = record

    def get(self, complaint_id: str) -> ComplaintLifecycleRecord | None:
        return self._records.get(complaint_id)