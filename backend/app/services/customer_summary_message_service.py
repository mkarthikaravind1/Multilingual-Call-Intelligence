from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.domain.customer_contact import CustomerContact, MessagingChannel
from app.domain.post_call_summary import PostCallSummary


@dataclass(frozen=True)
class CustomerSummaryMessage:
    message_id: str
    customer_id: str
    call_id: str
    channel: MessagingChannel
    content: str
    created_at: float

    def __post_init__(self) -> None:
        if not self.message_id.strip():
            raise ValueError("message_id must not be empty.")
        if not self.customer_id.strip():
            raise ValueError("customer_id must not be empty.")
        if not self.call_id.strip():
            raise ValueError("call_id must not be empty.")
        if not isinstance(self.channel, MessagingChannel):
            raise TypeError(
                f"channel must be a MessagingChannel, got {type(self.channel).__name__}."
            )
        if not self.content.strip():
            raise ValueError("content must not be empty.")
        if self.created_at < 0:
            raise ValueError("created_at must not be negative.")


class CustomerSummaryMessageService:
    """Creates customer-safe messages from a completed call summary.

    This intentionally keeps the delivery orchestration separate from the
    provider-specific transport code; the only contract here is the content to
    be sent to a customer who has explicitly granted consent.
    """

    def __init__(self, default_channel: MessagingChannel = MessagingChannel.SMS):
        self._default_channel = default_channel

    def build_message(
        self,
        summary: PostCallSummary,
        contact: CustomerContact,
        channel: MessagingChannel | None = None,
    ) -> CustomerSummaryMessage:
        if not isinstance(summary, PostCallSummary):
            raise TypeError(
                f"summary must be a PostCallSummary, got {type(summary).__name__}."
            )
        if not isinstance(contact, CustomerContact):
            raise TypeError(
                f"contact must be a CustomerContact, got {type(contact).__name__}."
            )

        selected_channel = self._default_channel if channel is None else channel
        if not isinstance(selected_channel, MessagingChannel):
            raise TypeError(
                "channel must be a MessagingChannel, "
                f"got {type(selected_channel).__name__}."
            )

        if not contact.can_receive_summary(selected_channel):
            raise PermissionError(
                f"Customer {contact.customer_id} has not granted consent for "
                f"{selected_channel.value} summaries."
            )

        content = self._format_message(summary, contact, selected_channel)
        return CustomerSummaryMessage(
            message_id=f"msg-{uuid4()}",
            customer_id=contact.customer_id,
            call_id=summary.call_id,
            channel=selected_channel,
            content=content,
            created_at=__import__("time").time(),
        )

    def _format_message(
        self,
        summary: PostCallSummary,
        contact: CustomerContact,
        channel: MessagingChannel,
    ) -> str:
        customer_text = summary.customer_summary.strip()
        prefix = (
            "Hi there, here is your call summary.\n\n"
            if contact.language is None or contact.language.lower() == "en"
            else f"Hello, here is your summary.\n\n"
        )
        if channel == MessagingChannel.WHATSAPP:
            return f"{prefix}{customer_text}"
        return f"{prefix}{customer_text}"
