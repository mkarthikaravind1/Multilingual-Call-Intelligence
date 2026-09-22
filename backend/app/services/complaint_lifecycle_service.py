from app.domain.complaint_lifecycle import ComplaintLifecycleRecord, ComplaintLifecycleStatus
from app.domain.complaint_lifecycle_repository import ComplaintLifecycleRepository


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


class ComplaintLifecycleService:
    """Thin orchestration around ComplaintLifecycleRecord. All transition
    validity rules live on the domain model - this service only fetches,
    checks call_id ownership, and persists via the injected repository.
    """

    def __init__(self, repository: ComplaintLifecycleRepository) -> None:
        self._repository = repository

    def create(
        self,
        complaint_id: str,
        call_id: str,
        category: str,
        first_detected_at: float,
        status: ComplaintLifecycleStatus = ComplaintLifecycleStatus.RAISED,
        follow_up_required: bool = False,
        customer_id: str | None = None,
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
    ) -> ComplaintLifecycleRecord:
        record = self.get(complaint_id)
        if record.call_id != call_id:
            raise ComplaintLifecycleCallMismatchError(complaint_id, call_id, record.call_id)

        updated = record.transition_to(new_status, at=at, follow_up_required=follow_up_required)
        self._repository.save(updated)
        return updated