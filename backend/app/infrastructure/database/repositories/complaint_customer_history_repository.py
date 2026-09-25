from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.complaint_customer_history_repository import (
    ComplaintCustomerHistoryRepository,
)
from app.domain.complaint_lifecycle import ComplaintLifecycleRecord, ComplaintLifecycleStatus
from app.infrastructure.database.models import ComplaintLifecycleRecordModel
from app.infrastructure.database.repositories._complaint_lifecycle_mapping import (
    to_domain,
    to_model,
)

# Must match ComplaintCustomerHistoryRepository's in-memory implementation:
# RESOLVED is the only fully closed status; FOLLOW_UP still needs attention.
_CLOSED_STATUS_VALUES = {ComplaintLifecycleStatus.RESOLVED.value}


class PostgresComplaintCustomerHistoryRepository(ComplaintCustomerHistoryRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, record: ComplaintLifecycleRecord) -> None:
        with self._session_factory() as session, session.begin():
            existing = session.get(ComplaintLifecycleRecordModel, record.complaint_id)
            if existing is not None:
                session.delete(existing)
                session.flush()
            session.add(to_model(record))

    def get(self, complaint_id: str) -> ComplaintLifecycleRecord | None:
        with self._session_factory() as session:
            model = session.get(ComplaintLifecycleRecordModel, complaint_id)
            return None if model is None else to_domain(model)

    def get_active_for_customer(self, customer_id: str) -> tuple[ComplaintLifecycleRecord, ...]:
        with self._session_factory() as session:
            stmt = (
                select(ComplaintLifecycleRecordModel)
                .where(
                    ComplaintLifecycleRecordModel.customer_id == customer_id,
                    ComplaintLifecycleRecordModel.status.not_in(_CLOSED_STATUS_VALUES),
                )
                .order_by(ComplaintLifecycleRecordModel.first_detected_at)
            )
            models = session.scalars(stmt).all()
            return tuple(to_domain(model) for model in models)

    def get_history_for_customer(self, customer_id: str) -> tuple[ComplaintLifecycleRecord, ...]:
        with self._session_factory() as session:
            stmt = (
                select(ComplaintLifecycleRecordModel)
                .where(ComplaintLifecycleRecordModel.customer_id == customer_id)
                .order_by(ComplaintLifecycleRecordModel.first_detected_at)
            )
            models = session.scalars(stmt).all()
            return tuple(to_domain(model) for model in models)