from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from time import time
from uuid import uuid4

from app.domain.customer_contact import ConsentStatus, CustomerContact, MessagingChannel
from app.domain.customer_summary_delivery import CustomerSummaryDelivery, DeliveryStatus
from app.domain.post_call_summary import PostCallSummary
from app.services.customer_summary_message_service import CustomerSummaryMessageService
from app.services.customer_summary_repository import CustomerSummaryDeliveryRepository


class CustomerSummaryDeliveryProvider(ABC):
    @abstractmethod
    def send_summary(
        self,
        contact: CustomerContact,
        message: str,
        channel: MessagingChannel,
    ) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class CustomerSummaryDeliveryRequest:
    contact: CustomerContact
    summary: PostCallSummary
    channel: MessagingChannel
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.contact, CustomerContact):
            raise TypeError(
                f"contact must be a CustomerContact, got {type(self.contact).__name__}."
            )
        if not isinstance(self.summary, PostCallSummary):
            raise TypeError(
                f"summary must be a PostCallSummary, got {type(self.summary).__name__}."
            )
        if not isinstance(self.channel, MessagingChannel):
            raise TypeError(
                f"channel must be a MessagingChannel, got {type(self.channel).__name__}."
            )
        if not self.message.strip():
            raise ValueError("message must not be empty.")


class CustomerSummaryDeliveryService:
    def __init__(
        self,
        provider: CustomerSummaryDeliveryProvider,
        message_service: CustomerSummaryMessageService | None = None,
        repository: CustomerSummaryDeliveryRepository | None = None,
        require_consent: bool = True,
    ):
        self._provider = provider
        self._message_service = message_service
        self._repository = repository
        self._require_consent = require_consent

    def _idempotency_key(self, contact: CustomerContact, call_id: str, channel: MessagingChannel) -> str:
        return f"customer-summary:{call_id}:{contact.customer_id}:{channel.value}"

    def _persist(self, delivery: CustomerSummaryDelivery) -> CustomerSummaryDelivery:
        if self._repository is not None:
            self._repository.save(delivery)
        return delivery

    def _record_failure(
        self,
        request: CustomerSummaryDeliveryRequest,
        *,
        reason: str,
        error: str | None,
        provider_message_id: str | None = None,
    ) -> CustomerSummaryDelivery:
        now = time()
        delivery = CustomerSummaryDelivery(
            delivery_id=f"delivery-{uuid4()}",
            customer_id=request.contact.customer_id,
            call_id=request.summary.call_id,
            channel=request.channel,
            status=DeliveryStatus.FAILED,
            message=request.message,
            provider=self._provider.__class__.__name__,
            provider_message_id=provider_message_id,
            idempotency_key=self._idempotency_key(
                request.contact,
                request.summary.call_id,
                request.channel,
            ),
            attempts=1,
            created_at=now,
            updated_at=now,
            failure_reason=reason,
            last_error=error,
        )
        return self._persist(delivery)

    def send_summary_to_customer(
        self,
        summary: PostCallSummary,
        contact: CustomerContact,
        channel: MessagingChannel | None = None,
    ) -> CustomerSummaryDelivery:
        selected_channel = contact.preferred_channel if channel is None else channel
        message = (
            self._message_service.build_message(summary, contact, selected_channel).content
            if self._message_service is not None
            else summary.customer_summary
        )

        return self.send(
            CustomerSummaryDeliveryRequest(
                contact=contact,
                summary=summary,
                channel=selected_channel,
                message=message,
            )
        )

    def send(self, request: CustomerSummaryDeliveryRequest) -> CustomerSummaryDelivery:
        if not isinstance(request, CustomerSummaryDeliveryRequest):
            raise TypeError(
                f"request must be a CustomerSummaryDeliveryRequest, got {type(request).__name__}."
            )

        idempotency_key = self._idempotency_key(
            request.contact,
            request.summary.call_id,
            request.channel,
        )
        if self._repository is not None:
            existing = self._repository.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing

        now = time()
        existing = None
        if self._repository is not None:
            existing = self._repository.get_latest_by_call_id(request.summary.call_id)
        if existing is not None and existing.customer_id == request.contact.customer_id:
            return existing

        can_receive = request.contact.can_receive_summary(request.channel)
        if self._require_consent and not can_receive:
            rejected = CustomerSummaryDelivery(
                delivery_id=f"delivery-{uuid4()}",
                customer_id=request.contact.customer_id,
                call_id=request.summary.call_id,
                channel=request.channel,
                status=DeliveryStatus.REJECTED,
                message=request.message,
                provider=self._provider.__class__.__name__,
                idempotency_key=idempotency_key,
                attempts=1,
                created_at=now,
                updated_at=now,
                failure_reason="customer_consent_missing",
                last_error="Customer consent is not granted for this channel.",
            )
            return self._persist(rejected)

        if not self._require_consent and request.contact.consent_status == ConsentStatus.UNKNOWN:
            can_receive = True

        if not can_receive:
            rejected = CustomerSummaryDelivery(
                delivery_id=f"delivery-{uuid4()}",
                customer_id=request.contact.customer_id,
                call_id=request.summary.call_id,
                channel=request.channel,
                status=DeliveryStatus.REJECTED,
                message=request.message,
                provider=self._provider.__class__.__name__,
                idempotency_key=idempotency_key,
                attempts=1,
                created_at=now,
                updated_at=now,
                failure_reason="customer_not_eligible",
                last_error="Customer is not eligible to receive a summary.",
            )
            return self._persist(rejected)

        try:
            provider_message_id = self._provider.send_summary(
                request.contact,
                request.message,
                request.channel,
            )
            sent = CustomerSummaryDelivery(
                delivery_id=f"delivery-{uuid4()}",
                customer_id=request.contact.customer_id,
                call_id=request.summary.call_id,
                channel=request.channel,
                status=DeliveryStatus.SENT,
                message=request.message,
                provider=self._provider.__class__.__name__,
                provider_message_id=provider_message_id,
                idempotency_key=idempotency_key,
                attempts=1,
                created_at=now,
                updated_at=now,
            )
            return self._persist(sent)
        except Exception as exc:
            error_text = str(exc)
            if len(error_text) > 500:
                error_text = error_text[:497] + "..."
            failed = CustomerSummaryDelivery(
                delivery_id=f"delivery-{uuid4()}",
                customer_id=request.contact.customer_id,
                call_id=request.summary.call_id,
                channel=request.channel,
                status=DeliveryStatus.FAILED,
                message=request.message,
                provider=self._provider.__class__.__name__,
                idempotency_key=idempotency_key,
                attempts=1,
                created_at=now,
                updated_at=now,
                failure_reason="provider_delivery_failed",
                last_error=error_text,
            )
            return self._persist(failed)
