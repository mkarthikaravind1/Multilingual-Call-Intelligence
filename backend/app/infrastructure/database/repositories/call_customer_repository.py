from sqlalchemy.orm import Session, sessionmaker

from app.domain.call_customer import CallCustomerLink
from app.infrastructure.database.models import CallCustomerModel
from app.services.call_customer_repository import CallCustomerRepository


class PostgresCallCustomerRepository(CallCustomerRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, call_id: str) -> CallCustomerLink | None:
        with self._session_factory() as session:
            model = session.get(CallCustomerModel, call_id)
            if model is None:
                return None
            return CallCustomerLink(
                call_id=model.call_id,
                caller_number=model.caller_number,
                customer_id=model.customer_id,
                vehicle_id=model.vehicle_id,
                updated_at=model.updated_at,
            )

    def save(self, link: CallCustomerLink) -> None:
        with self._session_factory() as session, session.begin():
            session.merge(
                CallCustomerModel(
                    call_id=link.call_id,
                    caller_number=link.caller_number,
                    customer_id=link.customer_id,
                    vehicle_id=link.vehicle_id,
                    updated_at=link.updated_at,
                )
            )
