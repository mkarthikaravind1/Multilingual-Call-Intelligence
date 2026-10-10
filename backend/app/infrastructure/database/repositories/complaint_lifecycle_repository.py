from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.complaint_lifecycle import (
    ComplaintLifecycleEvent,
    ComplaintLifecycleRecord,
    ComplaintLifecycleStatus,
)
from app.domain.complaint_lifecycle_repository import ComplaintLifecycleRepository
from app.infrastructure.database.models import (
    ComplaintLifecycleEventModel,
    ComplaintLifecycleRecordModel,
)
from app.infrastructure.database.repositories._complaint_lifecycle_mapping import (
    to_domain,
    to_model,
)
from app.infrastructure.database.repositories._saving import save_row

_RECORD_ORDER = (
    ComplaintLifecycleRecordModel.first_detected_at,
    ComplaintLifecycleRecordModel.complaint_id,
)


class PostgresComplaintLifecycleRepository(ComplaintLifecycleRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, record: ComplaintLifecycleRecord) -> None:
        save_row(self._session_factory, to_model(record))

    def get(self, complaint_id: str) -> ComplaintLifecycleRecord | None:
        with self._session_factory() as session:
            model = session.get(ComplaintLifecycleRecordModel, complaint_id)
            return None if model is None else to_domain(model)

    def list_for_call(self, call_id: str) -> tuple[ComplaintLifecycleRecord, ...]:
        return self._select(ComplaintLifecycleRecordModel.call_id == call_id)

    def list_for_customer(self, customer_id: str) -> tuple[ComplaintLifecycleRecord, ...]:
        return self._select(ComplaintLifecycleRecordModel.customer_id == customer_id)

    def list_by_status(
        self, statuses: Iterable[ComplaintLifecycleStatus]
    ) -> tuple[ComplaintLifecycleRecord, ...]:
        values = [status.value for status in statuses]
        return self._select(ComplaintLifecycleRecordModel.status.in_(values))

    def add_event(self, event: ComplaintLifecycleEvent) -> None:
        with self._session_factory() as session, session.begin():
            session.add(
                ComplaintLifecycleEventModel(
                    complaint_id=event.complaint_id,
                    status=event.status.value,
                    at=event.at,
                    actor=event.actor,
                    note=event.note,
                )
            )

    def list_events(
        self, complaint_ids: Iterable[str]
    ) -> dict[str, tuple[ComplaintLifecycleEvent, ...]]:
        ids = list(complaint_ids)
        if not ids:
            return {}
        with self._session_factory() as session:
            stmt = (
                select(ComplaintLifecycleEventModel)
                .where(ComplaintLifecycleEventModel.complaint_id.in_(ids))
                .order_by(ComplaintLifecycleEventModel.at, ComplaintLifecycleEventModel.id)
            )
            events: dict[str, list[ComplaintLifecycleEvent]] = {}
            for model in session.scalars(stmt):
                events.setdefault(model.complaint_id, []).append(
                    ComplaintLifecycleEvent(
                        complaint_id=model.complaint_id,
                        status=ComplaintLifecycleStatus(model.status),
                        at=model.at,
                        actor=model.actor,
                        note=model.note,
                    )
                )
            return {complaint_id: tuple(items) for complaint_id, items in events.items()}

    def _select(self, condition) -> tuple[ComplaintLifecycleRecord, ...]:
        with self._session_factory() as session:
            stmt = select(ComplaintLifecycleRecordModel).where(condition).order_by(*_RECORD_ORDER)
            return tuple(to_domain(model) for model in session.scalars(stmt))
