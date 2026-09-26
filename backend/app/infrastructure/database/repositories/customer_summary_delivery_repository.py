from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.customer_contact import MessagingChannel
from app.domain.customer_summary_delivery import (
    CustomerSummaryDelivery,
    DeliveryStatus,
)
from app.services.customer_summary_repository import CustomerSummaryDeliveryRepository
from app.infrastructure.database.models import CustomerSummaryDeliveryModel


def _to_domain(model: CustomerSummaryDeliveryModel) -> CustomerSummaryDelivery:
    return CustomerSummaryDelivery(
        delivery_id=model.delivery_id,
        customer_id=model.customer_id,
        call_id=model.call_id,
        channel=MessagingChannel(model.channel),
        status=DeliveryStatus(model.status),
        message=model.message,
        provider=model.provider,
        provider_message_id=model.provider_message_id,
        idempotency_key=model.idempotency_key,
        attempts=model.attempts,
        created_at=model.created_at,
        updated_at=model.updated_at,
        failure_reason=model.failure_reason,
        last_error=model.last_error,
    )


def _to_model(delivery: CustomerSummaryDelivery) -> CustomerSummaryDeliveryModel:
    return CustomerSummaryDeliveryModel(
        delivery_id=delivery.delivery_id,
        customer_id=delivery.customer_id,
        call_id=delivery.call_id,
        channel=delivery.channel.value,
        status=delivery.status.value,
        message=delivery.message,
        provider=delivery.provider,
        provider_message_id=delivery.provider_message_id,
        idempotency_key=delivery.idempotency_key,
        attempts=delivery.attempts,
        created_at=delivery.created_at,
        updated_at=delivery.updated_at,
        failure_reason=delivery.failure_reason,
        last_error=delivery.last_error,
    )


class PostgresCustomerSummaryDeliveryRepository(CustomerSummaryDeliveryRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, delivery: CustomerSummaryDelivery) -> None:
        with self._session_factory() as session, session.begin():
            existing = session.get(CustomerSummaryDeliveryModel, delivery.delivery_id)
            if existing is not None:
                session.delete(existing)
                session.flush()
            session.add(_to_model(delivery))

    def get_by_call_id(self, call_id: str) -> tuple[CustomerSummaryDelivery, ...]:
        with self._session_factory() as session:
            models = session.scalars(
                select(CustomerSummaryDeliveryModel).where(
                    CustomerSummaryDeliveryModel.call_id == call_id
                )
            ).all()
            return tuple(_to_domain(model) for model in models)

    def get_by_idempotency_key(self, idempotency_key: str) -> CustomerSummaryDelivery | None:
        with self._session_factory() as session:
            model = session.scalar(
                select(CustomerSummaryDeliveryModel).where(
                    CustomerSummaryDeliveryModel.idempotency_key == idempotency_key
                )
            )
            return None if model is None else _to_domain(model)

    def get_latest_by_call_id(self, call_id: str) -> CustomerSummaryDelivery | None:
        with self._session_factory() as session:
            model = session.scalar(
                select(CustomerSummaryDeliveryModel)
                .where(CustomerSummaryDeliveryModel.call_id == call_id)
                .order_by(
                    CustomerSummaryDeliveryModel.updated_at.desc(),
                    CustomerSummaryDeliveryModel.created_at.desc(),
                )
            )
            return None if model is None else _to_domain(model)
