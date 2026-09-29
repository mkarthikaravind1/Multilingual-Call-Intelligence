from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.escalation import (
    Escalation,
    EscalationLevel,
    EscalationSignal,
    EscalationSignalType,
    EscalationStatus,
)
from app.infrastructure.database.models import EscalationModel
from app.services.escalation_repository import EscalationRepository


def _to_model(escalation: Escalation) -> EscalationModel:
    return EscalationModel(
        call_id=escalation.call_id,
        level=escalation.level.value,
        status=escalation.status.value,
        signals=[
            {
                "type": signal.signal_type.value,
                "level": signal.level.value,
                "description": signal.description,
                "evidence": signal.evidence,
            }
            for signal in escalation.signals
        ],
        first_detected_at=escalation.first_detected_at,
        updated_at=escalation.updated_at,
        acknowledged_by=escalation.acknowledged_by,
        acknowledged_at=escalation.acknowledged_at,
        resolved_by=escalation.resolved_by,
        resolved_at=escalation.resolved_at,
        resolution_note=escalation.resolution_note,
    )


def _to_domain(model: EscalationModel) -> Escalation:
    return Escalation(
        call_id=model.call_id,
        level=EscalationLevel(model.level),
        status=EscalationStatus(model.status),
        signals=tuple(
            EscalationSignal(
                signal_type=EscalationSignalType(signal["type"]),
                level=EscalationLevel(signal["level"]),
                description=signal["description"],
                evidence=signal.get("evidence"),
            )
            for signal in model.signals
        ),
        first_detected_at=model.first_detected_at,
        updated_at=model.updated_at,
        acknowledged_by=model.acknowledged_by,
        acknowledged_at=model.acknowledged_at,
        resolved_by=model.resolved_by,
        resolved_at=model.resolved_at,
        resolution_note=model.resolution_note,
    )


class PostgresEscalationRepository(EscalationRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, call_id: str) -> Escalation | None:
        with self._session_factory() as session:
            model = session.get(EscalationModel, call_id)
            return None if model is None else _to_domain(model)

    def get_many(self, call_ids: Iterable[str]) -> dict[str, Escalation]:
        ids = list(call_ids)
        if not ids:
            return {}
        with self._session_factory() as session:
            models = session.scalars(
                select(EscalationModel).where(EscalationModel.call_id.in_(ids))
            ).all()
            return {model.call_id: _to_domain(model) for model in models}

    def save(self, escalation: Escalation) -> None:
        with self._session_factory() as session, session.begin():
            session.merge(_to_model(escalation))

    def list_by_status(self, statuses: Iterable[EscalationStatus]) -> tuple[Escalation, ...]:
        values = [status.value for status in statuses]
        with self._session_factory() as session:
            models = session.scalars(
                select(EscalationModel).where(EscalationModel.status.in_(values))
            ).all()
            return tuple(_to_domain(model) for model in models)
