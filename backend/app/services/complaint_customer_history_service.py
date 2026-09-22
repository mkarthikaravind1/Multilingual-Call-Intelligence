from app.domain.complaint_customer_history_repository import ComplaintCustomerHistoryRepository
from app.domain.complaint_lifecycle import ComplaintLifecycleRecord


class ComplaintCustomerHistoryService:
    """Thin orchestration over ComplaintCustomerHistoryRepository."""

    def __init__(self, repository: ComplaintCustomerHistoryRepository) -> None:
        self._repository = repository

    def save(self, record: ComplaintLifecycleRecord) -> None:
        self._repository.save(record)

    def get(self, complaint_id: str) -> ComplaintLifecycleRecord | None:
        return self._repository.get(complaint_id)

    def get_active_for_customer(self, customer_id: str) -> tuple[ComplaintLifecycleRecord, ...]:
        return self._repository.get_active_for_customer(customer_id)

    def get_history_for_customer(self, customer_id: str) -> tuple[ComplaintLifecycleRecord, ...]:
        return self._repository.get_history_for_customer(customer_id)