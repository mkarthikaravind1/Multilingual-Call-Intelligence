"""Mapping shared by ComplaintLifecycleRepository and
ComplaintCustomerHistoryRepository: both persist the same
ComplaintLifecycleRecord aggregate, just queried differently, so they
back onto the same table instead of duplicating storage.
"""

from app.domain.complaint_lifecycle import ComplaintLifecycleRecord, ComplaintLifecycleStatus
from app.infrastructure.database.models import ComplaintLifecycleRecordModel


def to_domain(model: ComplaintLifecycleRecordModel) -> ComplaintLifecycleRecord:
    return ComplaintLifecycleRecord(
        complaint_id=model.complaint_id,
        call_id=model.call_id,
        category=model.category,
        status=ComplaintLifecycleStatus(model.status),
        first_detected_at=model.first_detected_at,
        last_updated_at=model.last_updated_at,
        follow_up_required=model.follow_up_required,
        customer_id=model.customer_id,
    )


def to_model(record: ComplaintLifecycleRecord) -> ComplaintLifecycleRecordModel:
    return ComplaintLifecycleRecordModel(
        complaint_id=record.complaint_id,
        call_id=record.call_id,
        category=record.category,
        status=record.status.value,
        first_detected_at=record.first_detected_at,
        last_updated_at=record.last_updated_at,
        follow_up_required=record.follow_up_required,
        customer_id=record.customer_id,
    )