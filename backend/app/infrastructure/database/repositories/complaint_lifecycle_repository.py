from sqlalchemy.orm import Session, sessionmaker

from app.domain.complaint_lifecycle import ComplaintLifecycleRecord
from app.domain.complaint_lifecycle_repository import ComplaintLifecycleRepository
from app.infrastructure.database.models import ComplaintLifecycleRecordModel
from app.infrastructure.database.repositories._complaint_lifecycle_mapping import (
    to_domain,
    to_model,
)


class PostgresComplaintLifecycleRepository(ComplaintLifecycleRepository):
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