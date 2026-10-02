from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.call_customer import CallCustomerLink
from app.infrastructure.database.models import CallCustomerModel
from app.services.call_customer_repository import CallCustomerRepository


def _to_domain(model: CallCustomerModel) -> CallCustomerLink:
    return CallCustomerLink(
        call_id=model.call_id,
        caller_number=model.caller_number,
        customer_id=model.customer_id,
        vehicle_id=model.vehicle_id,
        updated_at=model.updated_at,
        customer_name=model.customer_name,
        vehicle_registration=model.vehicle_registration,
    )


class PostgresCallCustomerRepository(CallCustomerRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, call_id: str) -> CallCustomerLink | None:
        with self._session_factory() as session:
            model = session.get(CallCustomerModel, call_id)
            return None if model is None else _to_domain(model)

    def save(self, link: CallCustomerLink) -> None:
        with self._session_factory() as session, session.begin():
            session.merge(
                CallCustomerModel(
                    call_id=link.call_id,
                    caller_number=link.caller_number,
                    customer_id=link.customer_id,
                    vehicle_id=link.vehicle_id,
                    updated_at=link.updated_at,
                    customer_name=link.customer_name,
                    vehicle_registration=link.vehicle_registration,
                )
            )

    def get_many(self, call_ids: Iterable[str]) -> dict[str, CallCustomerLink]:
        ids = list(set(call_ids))
        if not ids:
            return {}
        with self._session_factory() as session:
            models = session.scalars(
                select(CallCustomerModel).where(CallCustomerModel.call_id.in_(ids))
            ).all()
            return {model.call_id: _to_domain(model) for model in models}

    def list_without_customer_name(self) -> tuple[CallCustomerLink, ...]:
        with self._session_factory() as session:
            models = session.scalars(
                select(CallCustomerModel)
                .where(
                    CallCustomerModel.customer_name.is_(None),
                    or_(
                        CallCustomerModel.caller_number.is_not(None),
                        CallCustomerModel.customer_id.is_not(None),
                    ),
                )
                .order_by(CallCustomerModel.call_id)
            ).all()
            return tuple(_to_domain(model) for model in models)
