from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from time import time

from app.domain.customer_contact import ConsentStatus, CustomerContact, MessagingChannel
from app.domain.customer_summary_delivery import CustomerSummaryDelivery, DeliveryStatus
from app.domain.post_call_summary import PostCallSummary
from app.services.customer_summary_delivery_records import (
    CUSTOMER_LOOKUP_FAILED,
    QUEUED_STALE_SECONDS,
    RETRY_WINDOW_SECONDS,
    UNKNOWN_CUSTOMER_ID,
    CustomerSummaryDeliveryRecords,
    error_text,
)
from app.services.customer_summary_message_service import CustomerSummaryMessageService
from app.services.customer_summary_repository import CustomerSummaryDeliveryRepository

logger = logging.getLogger(__name__)

# The record-keeping rules are also importable from here, where they began.
__all__ = [
    "CUSTOMER_LOOKUP_FAILED",
    "QUEUED_STALE_SECONDS",
    "RETRY_WINDOW_SECONDS",
    "UNKNOWN_CUSTOMER_ID",
    "CustomerSummaryDeliveryProvider",
    "CustomerSummaryDeliveryService",
]


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


class CustomerSummaryDeliveryService:
    """Sends a call's summary to its customer: who may receive it, on which
    channel, and handing it to the provider. What is recorded about each
    delivery, and when one may be tried again, is
    CustomerSummaryDeliveryRecords' business."""

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
        self._require_consent = require_consent
        self._records = CustomerSummaryDeliveryRecords(
            repository, provider.__class__.__name__, max_attempts
        )

    def list_for_call(self, call_id: str) -> tuple[CustomerSummaryDelivery, ...]:
        """Delivery records for a call, most recent first."""
        return self._records.for_call(call_id)

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
            return self._records.record_lookup_failure(
                summary, self._deliverable_channel(MessagingChannel.SMS), exc
            )
        if contact is None:
            return self._records.close_unfinished(summary.call_id)
        return self.send_summary_to_customer(summary=summary, contact=contact)

    def retry_unfinished(
        self,
        get_summary: Callable[[str], PostCallSummary | None],
        resolve_contact: Callable[[str], CustomerContact | None],
    ) -> int:
        """Try again the deliveries that failed (or were interrupted) and
        still have attempts left. Returns how many were sent."""
        sent = 0
        for delivery in self._records.retryable(time()):
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

    # --- Sending ---

    def send_summary_to_customer(
        self,
        summary: PostCallSummary,
        contact: CustomerContact,
        channel: MessagingChannel | None = None,
    ) -> CustomerSummaryDelivery:
        """Send once. A delivery already made (or refused) for this call
        and customer is returned as it is; one that failed is attempted
        again while it has attempts left."""
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
                # No consent: _send() makes that decision and records the
                # rejection; the message is never handed to the provider.
                pass
        if not message.strip():
            raise ValueError("message must not be empty.")
        return self._send(summary.call_id, contact, selected_channel, message)

    def _send(
        self, call_id: str, contact: CustomerContact, channel: MessagingChannel, message: str
    ) -> CustomerSummaryDelivery:
        now = time()
        idempotency_key = f"customer-summary:{call_id}:{contact.customer_id}:{channel.value}"
        existing = self._records.existing(call_id, contact.customer_id, idempotency_key)
        if existing is not None and not self._records.may_retry(existing, now):
            return existing

        delivery = self._records.claim(
            call_id=call_id,
            customer_id=contact.customer_id,
            channel=channel,
            message=message,
            idempotency_key=idempotency_key,
            existing=existing,
            now=now,
        )
        if delivery is None:
            # Another run got the record first: its delivery is the answer.
            return (
                self._records.existing(call_id, contact.customer_id, idempotency_key)
                or existing  # type: ignore[return-value]
            )

        rejection = self._rejection(contact, channel)
        if rejection is not None:
            reason, error = rejection
            return self._records.finish(
                delivery, DeliveryStatus.REJECTED, failure_reason=reason, last_error=error
            )

        try:
            provider_message_id = self._provider.send_summary_once(
                contact, message, channel, idempotency_key
            )
        except Exception as exc:
            return self._records.finish(
                delivery,
                DeliveryStatus.FAILED,
                failure_reason="provider_delivery_failed",
                last_error=error_text(exc),
            )
        return self._records.finish(
            delivery, DeliveryStatus.SENT, provider_message_id=provider_message_id
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

    def _rejection(
        self, contact: CustomerContact, channel: MessagingChannel
    ) -> tuple[str, str] | None:
        """Why this must not be sent (reason, explanation), or None."""
        if not self._provider.delivers:
            return "delivery_not_configured", "No delivery provider is configured."

        can_receive = contact.can_receive_summary(channel)
        if self._require_consent and not can_receive:
            return "customer_consent_missing", "Customer consent is not granted for this channel."
        if not self._require_consent and contact.consent_status == ConsentStatus.UNKNOWN:
            can_receive = True
        if not can_receive:
            return "customer_not_eligible", "Customer is not eligible to receive a summary."
        return None
