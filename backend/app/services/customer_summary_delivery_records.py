"""What is recorded about each call's summary delivery, and when one may be
tried again. CustomerSummaryDeliveryService decides and sends; this keeps
the books."""

from __future__ import annotations

from dataclasses import replace
from time import time
from uuid import uuid4

from app.domain.customer_contact import MessagingChannel
from app.domain.customer_summary_delivery import CustomerSummaryDelivery, DeliveryStatus
from app.domain.post_call_summary import PostCallSummary
from app.services.customer_summary_repository import CustomerSummaryDeliveryRepository

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
_UNFINISHED = (DeliveryStatus.FAILED, DeliveryStatus.QUEUED)


class CustomerSummaryDeliveryRecords:
    """repository None: nothing is kept (every delivery is new, and none
    is ever retried)."""

    def __init__(
        self,
        repository: CustomerSummaryDeliveryRepository | None,
        provider_name: str,
        max_attempts: int = 5,
    ) -> None:
        self._repository = repository
        self._provider_name = provider_name
        # How many times one delivery is attempted before it stays failed.
        self._max_attempts = max(1, max_attempts)

    def for_call(self, call_id: str) -> tuple[CustomerSummaryDelivery, ...]:
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

    def existing(
        self, call_id: str, customer_id: str, idempotency_key: str
    ) -> CustomerSummaryDelivery | None:
        """The delivery already recorded for this call and customer."""
        if self._repository is None:
            return None
        existing = self._repository.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing
        latest = self._repository.get_latest_by_call_id(call_id)
        if latest is not None and (
            latest.customer_id == customer_id
            # Recorded while the customer could not be looked up: this is
            # that delivery, now that we know who it is for.
            or latest.failure_reason == CUSTOMER_LOOKUP_FAILED
        ):
            return latest
        return None

    def may_retry(self, delivery: CustomerSummaryDelivery, now: float) -> bool:
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

    def retryable(self, now: float) -> tuple[CustomerSummaryDelivery, ...]:
        """Deliveries that failed (or were interrupted) and may be tried
        again, the longest untouched first."""
        if self._repository is None:
            return ()
        # Only those that can still be tried: the ones that used up their
        # attempts or their day would otherwise fill every batch.
        unfinished = self._repository.list_unfinished(
            _RETRY_BATCH,
            max_attempts=self._max_attempts,
            created_after=now - RETRY_WINDOW_SECONDS,
        )
        return tuple(delivery for delivery in unfinished if self.may_retry(delivery, now))

    def claim(
        self,
        *,
        call_id: str,
        customer_id: str,
        channel: MessagingChannel,
        message: str,
        idempotency_key: str,
        existing: CustomerSummaryDelivery | None,
        now: float,
    ) -> CustomerSummaryDelivery | None:
        """The delivery record, marked queued for this attempt; None when
        another run got it first. Recorded before anything is sent: of two
        runs for the same call (a retry overlapping the first attempt),
        only the one that gets the record sends."""
        if existing is None:
            queued = CustomerSummaryDelivery(
                delivery_id=f"delivery-{uuid4()}",
                customer_id=customer_id,
                call_id=call_id,
                channel=channel,
                status=DeliveryStatus.QUEUED,
                message=message,
                provider=self._provider_name,
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
            customer_id=customer_id,
            channel=channel,
            status=DeliveryStatus.QUEUED,
            message=message,
            idempotency_key=idempotency_key,
            attempts=existing.attempts + 1,
            updated_at=now,
            failure_reason=None,
            last_error=None,
        )

    def finish(
        self,
        delivery: CustomerSummaryDelivery,
        status: DeliveryStatus,
        *,
        provider_message_id: str | None = None,
        failure_reason: str | None = None,
        last_error: str | None = None,
    ) -> CustomerSummaryDelivery:
        """Record how a claimed delivery ended."""
        return self._save(
            replace(
                delivery,
                status=status,
                provider_message_id=provider_message_id,
                updated_at=time(),
                failure_reason=failure_reason,
                last_error=last_error,
            )
        )

    def record_lookup_failure(
        self, summary: PostCallSummary, channel: MessagingChannel, error: Exception
    ) -> CustomerSummaryDelivery | None:
        """The call's customer could not be looked up: a failed delivery
        with no customer yet, so it is tried again."""
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
                channel=channel,
                status=DeliveryStatus.FAILED,
                message=summary.customer_summary,
                provider=self._provider_name,
                idempotency_key=key,
                attempts=1,
                created_at=now,
                updated_at=now,
                failure_reason=CUSTOMER_LOOKUP_FAILED,
                last_error=error_text(error),
            )
            self._repository.add_if_absent(failed)
            return failed
        if existing.status is not DeliveryStatus.FAILED:
            return existing
        return self._save(
            replace(
                existing,
                attempts=existing.attempts + 1,
                updated_at=now,
                last_error=error_text(error),
            )
        )

    def close_unfinished(self, call_id: str) -> CustomerSummaryDelivery | None:
        """The call turned out to have no known customer: stop retrying."""
        if self._repository is None:
            return None
        closed = None
        for delivery in self._repository.get_by_call_id(call_id):
            if delivery.status in _UNFINISHED:
                closed = self._save(
                    replace(
                        delivery,
                        status=DeliveryStatus.REJECTED,
                        updated_at=time(),
                        failure_reason="customer_not_identified",
                        last_error="The call has no identified customer to send the summary to.",
                    )
                )
        return closed

    def _save(self, delivery: CustomerSummaryDelivery) -> CustomerSummaryDelivery:
        if self._repository is not None:
            self._repository.save(delivery)
        return delivery


def error_text(error: Exception) -> str:
    text = str(error) or type(error).__name__
    if len(text) > _MAX_ERROR_LENGTH:
        text = text[: _MAX_ERROR_LENGTH - 3] + "..."
    return text
