from dataclasses import dataclass
from enum import Enum

from app.domain.customer_contact import MessagingChannel


class DeliveryStatus(str, Enum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CustomerSummaryDelivery:
    delivery_id: str
    customer_id: str
    call_id: str
    channel: MessagingChannel
    status: DeliveryStatus = DeliveryStatus.QUEUED
    message: str = ""
    provider: str | None = None
    provider_message_id: str | None = None
    idempotency_key: str | None = None
    attempts: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    failure_reason: str | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        if not self.delivery_id.strip():
            raise ValueError("delivery_id must not be empty.")
        if not self.customer_id.strip():
            raise ValueError("customer_id must not be empty.")
        if not self.call_id.strip():
            raise ValueError("call_id must not be empty.")
        if not isinstance(self.channel, MessagingChannel):
            raise TypeError(
                f"channel must be a MessagingChannel, got {type(self.channel).__name__}."
            )
        if not isinstance(self.status, DeliveryStatus):
            raise TypeError(
                f"status must be a DeliveryStatus, got {type(self.status).__name__}."
            )
        if self.provider is not None and not self.provider.strip():
            raise ValueError("provider must not be empty when provided.")
        if self.idempotency_key is not None and not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty when provided.")
        if self.attempts < 0:
            raise ValueError("attempts must not be negative.")
        if self.created_at < 0:
            raise ValueError("created_at must not be negative.")
        if self.updated_at < 0:
            raise ValueError("updated_at must not be negative.")
