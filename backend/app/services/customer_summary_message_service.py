from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import uuid4

from app.ai.summary.llm_provider import SAFE_CUSTOMER_MESSAGE
from app.domain.customer_contact import CustomerContact, MessagingChannel
from app.domain.post_call_summary import PostCallSummary
from app.messaging.sms_length import sms_parts

logger = logging.getLogger(__name__)


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

    def __init__(
        self,
        default_channel: MessagingChannel = MessagingChannel.SMS,
        sms_max_parts: int = 3,
    ):
        self._default_channel = default_channel
        # The longest SMS sent, in parts (a part is 153 Latin or 67 Tamil
        # characters): the summary text comes from an LLM, and each part
        # is a separate SMS from the gateway's SIM. 0 = no limit.
        self._sms_max_parts = sms_max_parts

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
        message = f"{prefix}{customer_text}"
        if channel != MessagingChannel.SMS or self._fits(message):
            return message
        # Too long for an SMS: first without the greeting line, then
        # the standard message instead of the summary.
        if self._fits(customer_text):
            return customer_text
        logger.warning(
            "Customer summary of call %s is %d SMS parts (limit %d); "
            "sending the standard message",
            summary.call_id,
            sms_parts(customer_text),
            self._sms_max_parts,
        )
        return SAFE_CUSTOMER_MESSAGE

    def _fits(self, text: str) -> bool:
        return self._sms_max_parts <= 0 or sms_parts(text) <= self._sms_max_parts
