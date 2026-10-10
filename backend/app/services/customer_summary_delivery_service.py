from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, replace
from time import time
from uuid import uuid4

from app.domain.customer_contact import ConsentStatus, CustomerContact, MessagingChannel
from app.domain.customer_summary_delivery import CustomerSummaryDelivery, DeliveryStatus
from app.domain.post_call_summary import PostCallSummary
from app.services.customer_summary_message_service import CustomerSummaryMessageService
from app.services.customer_summary_repository import CustomerSummaryDeliveryRepository

logger = logging.getLogger(__name__)

# Recorded while the customer of a call could not be looked up (e.g. the
# CRM was unreachable), so the delivery is tried again later.
UNKNOWN_CUSTOMER_ID = "unknown"
CUSTOMER_LOOKUP_FAILED = "customer_lookup_failed"
# A delivery left "queued" this long was interrupted (the process stopped
# between claiming it and recording the outcome) and may be tried again.
QUEUED_STALE_SECONDS = 600.0
# A delivery is only tried again this long after its call: a summary
# arriving days later would confuse the customer more than none.
RETRY_WINDOW_SECONDS = 24 * 60 * 60.0
_MAX_ERROR_LENGTH = 500
_RETRY_BATCH = 50


class CustomerSummaryDeliveryProvider(ABC):
    # Channels this provider can actually deliver on.
    supported_channels: frozenset[MessagingChannel] = frozenset(MessagingChannel)
    # False for a provider that sends nothing at all (delivery not set up):
    # its deliveries are recorded as not sent rather than as sent.
    delivers: bool = True

    @abstractmethod
    def send_summary(
        self,
        contact: CustomerContact,
        message: str,
        channel: MessagingChannel,
    ) -> str:
        raise NotImplementedError

    def send_summary_once(
        self,
        contact: CustomerContact,
        message: str,
        channel: MessagingChannel,
        delivery_key: str,
    ) -> str:
        """Like send_summary, for one delivery that may be attempted again
        (delivery_key is the same every time). A provider that can tell its
        gateway "this is the same message" overrides this, so a repeated
        attempt cannot reach the customer twice."""
        return self.send_summary(contact, message, channel)


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
        max_attempts: int = 5,
    ):
        self._provider = provider
        self._message_service = message_service
        self._repository = repository
        self._require_consent = require_consent
        # How many times one delivery is attempted before it stays failed.
        self._max_attempts = max(1, max_attempts)

    def list_for_call(self, call_id: str) -> tuple[CustomerSummaryDelivery, ...]:
        """Delivery records for a call, most recent first."""
        if self._repository is None:
            return ()
        return tuple(
            sorted(
                self._repository.get_by_call_id(call_id),
                key=lambda delivery: delivery.created_at,
                reverse=True,
            )
        )

    def _deliverable_channel(self, wanted: MessagingChannel) -> MessagingChannel:
        """The wanted channel if the provider can deliver on it; otherwise
        SMS, so a customer who prefers an unsupported channel still gets the
        summary rather than nothing."""
        supported = self._provider.supported_channels
        if wanted in supported or not supported:
            return wanted
        if MessagingChannel.SMS in supported:
            return MessagingChannel.SMS
        return sorted(supported, key=lambda c: c.value)[0]

    def _idempotency_key(self, contact: CustomerContact, call_id: str, channel: MessagingChannel) -> str:
        return f"customer-summary:{call_id}:{contact.customer_id}:{channel.value}"

    def _persist(self, delivery: CustomerSummaryDelivery) -> CustomerSummaryDelivery:
        if self._repository is not None:
            self._repository.save(delivery)
        return delivery

    # --- Delivering for a call ---

    def deliver_for_call(
        self,
        summary: PostCallSummary,
        resolve_contact: Callable[[str], CustomerContact | None],
    ) -> CustomerSummaryDelivery | None:
        """Send the call's summary to its customer. resolve_contact gives
        the customer (None: the call has no known customer, so there is
        nobody to send to) or raises when it cannot tell right now, in
        which case the delivery is recorded as failed and tried again."""
        try:
            contact = resolve_contact(summary.call_id)
        except Exception as exc:
            logger.warning(
                "Could not look up the customer of call %r to send the summary: %s",
                summary.call_id,
                type(exc).__name__,
            )
            return self._record_lookup_failure(summary, exc)
        if contact is None:
            return self._close_unfinished(summary.call_id)
        return self.send_summary_to_customer(summary=summary, contact=contact)

    def retry_unfinished(
        self,
        get_summary: Callable[[str], PostCallSummary | None],
        resolve_contact: Callable[[str], CustomerContact | None],
    ) -> int:
        """Try again the deliveries that failed (or were interrupted) and
        still have attempts left. Returns how many were sent."""
        if self._repository is None:
            return 0
        sent = 0
        now = time()
        # Only those that can still be tried: the ones that used up their
        # attempts or their day would otherwise fill every batch.
        retryable = self._repository.list_unfinished(
            _RETRY_BATCH,
            max_attempts=self._max_attempts,
            created_after=now - RETRY_WINDOW_SECONDS,
        )
        for delivery in retryable:
            if not self._may_retry(delivery, now):
                continue
            try:
                summary = get_summary(delivery.call_id)
                if summary is None:
                    continue
                result = self.deliver_for_call(summary, resolve_contact)
            except Exception:
                logger.exception(
                    "Retrying the customer summary of call %r failed", delivery.call_id
                )
                continue
            if result is not None and result.status is DeliveryStatus.SENT:
                sent += 1
        return sent

    def _record_lookup_failure(
        self, summary: PostCallSummary, error: Exception
    ) -> CustomerSummaryDelivery | None:
        if self._repository is None:
            return None
        now = time()
        key = f"customer-summary:{summary.call_id}:customer-lookup"
        existing = self._repository.get_by_idempotency_key(key)
        if existing is None:
            failed = CustomerSummaryDelivery(
                delivery_id=f"delivery-{uuid4()}",
                customer_id=UNKNOWN_CUSTOMER_ID,
                call_id=summary.call_id,
                channel=self._deliverable_channel(MessagingChannel.SMS),
                status=DeliveryStatus.FAILED,
                message=summary.customer_summary,
                provider=self._provider.__class__.__name__,
                idempotency_key=key,
                attempts=1,
                created_at=now,
                updated_at=now,
                failure_reason=CUSTOMER_LOOKUP_FAILED,
                last_error=_error_text(error),
            )
            self._repository.add_if_absent(failed)
            return failed
        if existing.status is not DeliveryStatus.FAILED:
            return existing
        return self._persist(
            replace(
                existing,
                attempts=existing.attempts + 1,
                updated_at=now,
                last_error=_error_text(error),
            )
        )

    def _close_unfinished(self, call_id: str) -> CustomerSummaryDelivery | None:
        """The call turned out to have no known customer: stop retrying."""
        if self._repository is None:
            return None
        closed = None
        for delivery in self._repository.get_by_call_id(call_id):
            if delivery.status in (DeliveryStatus.FAILED, DeliveryStatus.QUEUED):
                closed = self._persist(
                    replace(
                        delivery,
                        status=DeliveryStatus.REJECTED,
                        updated_at=time(),
                        failure_reason="customer_not_identified",
                        last_error="The call has no identified customer to send the summary to.",
                    )
                )
        return closed

    # --- Sending ---

    def send_summary_to_customer(
        self,
        summary: PostCallSummary,
        contact: CustomerContact,
        channel: MessagingChannel | None = None,
    ) -> CustomerSummaryDelivery:
        selected_channel = self._deliverable_channel(
            contact.preferred_channel if channel is None else channel
        )
        message = summary.customer_summary
        if self._message_service is not None:
            try:
                message = self._message_service.build_message(
                    summary, contact, selected_channel
                ).content
            except PermissionError:
                # No consent: send() makes that decision and records the
                # rejection; the message is never handed to the provider.
                pass

        return self.send(
            CustomerSummaryDeliveryRequest(
                contact=contact,
                summary=summary,
                channel=selected_channel,
                message=message,
            )
        )

    def send(self, request: CustomerSummaryDeliveryRequest) -> CustomerSummaryDelivery:
        """Send once. A delivery already made (or refused) for this call
        and customer is returned as it is; one that failed is attempted
        again while it has attempts left."""
        if not isinstance(request, CustomerSummaryDeliveryRequest):
            raise TypeError(
                f"request must be a CustomerSummaryDeliveryRequest, got {type(request).__name__}."
            )

        now = time()
        idempotency_key = self._idempotency_key(
            request.contact,
            request.summary.call_id,
            request.channel,
        )
        existing = self._existing_delivery(request, idempotency_key)
        if existing is not None and not self._may_retry(existing, now):
            return existing

        # Recorded as queued before anything is sent: of two runs for the
        # same call (a retry overlapping the first attempt), only the one
        # that gets the record sends.
        delivery = self._claim(request, idempotency_key, existing, now)
        if delivery is None:
            return self._existing_delivery(request, idempotency_key) or existing  # type: ignore[return-value]

        rejection = self._rejection(request)
        if rejection is not None:
            reason, error = rejection
            return self._finish(
                delivery, DeliveryStatus.REJECTED, failure_reason=reason, last_error=error
            )

        try:
            provider_message_id = self._provider.send_summary_once(
                request.contact,
                request.message,
                request.channel,
                idempotency_key,
            )
        except Exception as exc:
            return self._finish(
                delivery,
                DeliveryStatus.FAILED,
                failure_reason="provider_delivery_failed",
                last_error=_error_text(exc),
            )
        return self._finish(
            delivery, DeliveryStatus.SENT, provider_message_id=provider_message_id
        )

    def _existing_delivery(
        self, request: CustomerSummaryDeliveryRequest, idempotency_key: str
    ) -> CustomerSummaryDelivery | None:
        if self._repository is None:
            return None
        existing = self._repository.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing
        latest = self._repository.get_latest_by_call_id(request.summary.call_id)
        if latest is not None and (
            latest.customer_id == request.contact.customer_id
            # Recorded while the customer could not be looked up: this is
            # that delivery, now that we know who it is for.
            or latest.failure_reason == CUSTOMER_LOOKUP_FAILED
        ):
            return latest
        return None

    def _may_retry(self, delivery: CustomerSummaryDelivery, now: float) -> bool:
        if delivery.attempts >= self._max_attempts:
            return False
        if now - delivery.created_at > RETRY_WINDOW_SECONDS:
            return False
        if delivery.status is DeliveryStatus.FAILED:
            return True
        return (
            delivery.status is DeliveryStatus.QUEUED
            and now - delivery.updated_at >= QUEUED_STALE_SECONDS
        )

    def _claim(
        self,
        request: CustomerSummaryDeliveryRequest,
        idempotency_key: str,
        existing: CustomerSummaryDelivery | None,
        now: float,
    ) -> CustomerSummaryDelivery | None:
        """The delivery record, marked queued for this attempt; None when
        another run got it first."""
        if existing is None:
            queued = CustomerSummaryDelivery(
                delivery_id=f"delivery-{uuid4()}",
                customer_id=request.contact.customer_id,
                call_id=request.summary.call_id,
                channel=request.channel,
                status=DeliveryStatus.QUEUED,
                message=request.message,
                provider=self._provider.__class__.__name__,
                idempotency_key=idempotency_key,
                attempts=1,
                created_at=now,
                updated_at=now,
            )
            if self._repository is not None and not self._repository.add_if_absent(queued):
                return None
            return queued

        if self._repository is not None and not self._repository.claim_retry(
            existing.delivery_id, existing.attempts, now
        ):
            return None
        return replace(
            existing,
            customer_id=request.contact.customer_id,
            channel=request.channel,
            status=DeliveryStatus.QUEUED,
            message=request.message,
            idempotency_key=idempotency_key,
            attempts=existing.attempts + 1,
            updated_at=now,
            failure_reason=None,
            last_error=None,
        )

    def _rejection(self, request: CustomerSummaryDeliveryRequest) -> tuple[str, str] | None:
        """Why this must not be sent (reason, explanation), or None."""
        if not self._provider.delivers:
            return "delivery_not_configured", "No delivery provider is configured."

        can_receive = request.contact.can_receive_summary(request.channel)
        if self._require_consent and not can_receive:
            return "customer_consent_missing", "Customer consent is not granted for this channel."
        if not self._require_consent and request.contact.consent_status == ConsentStatus.UNKNOWN:
            can_receive = True
        if not can_receive:
            return "customer_not_eligible", "Customer is not eligible to receive a summary."
        return None

    def _finish(
        self,
        delivery: CustomerSummaryDelivery,
        status: DeliveryStatus,
        *,
        provider_message_id: str | None = None,
        failure_reason: str | None = None,
        last_error: str | None = None,
    ) -> CustomerSummaryDelivery:
        return self._persist(
            replace(
                delivery,
                status=status,
                provider_message_id=provider_message_id,
                updated_at=time(),
                failure_reason=failure_reason,
                last_error=last_error,
            )
        )


def _error_text(error: Exception) -> str:
    text = str(error) or type(error).__name__
    if len(text) > _MAX_ERROR_LENGTH:
        text = text[: _MAX_ERROR_LENGTH - 3] + "..."
    return text
