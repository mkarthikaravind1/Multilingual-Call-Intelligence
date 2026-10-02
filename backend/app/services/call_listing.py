"""The call list as people browse it: each call with who it was with, its
escalation and when its complaints were resolved, searchable and filterable.

A read model over several stores (conversations, call customers,
escalations, complaint lifecycle). PostgreSQL answers it with one query (see
app.infrastructure.database.repositories.call_listing_query); the in-memory
version below composes the in-memory repositories for tests and local runs.
"""

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.domain.complaint_lifecycle import (
    ComplaintLifecycleEvent,
    ComplaintLifecycleRecord,
    ComplaintLifecycleStatus,
)
from app.domain.complaint_lifecycle_repository import ComplaintLifecycleRepository
from app.domain.conversation import ConversationStatus
from app.domain.escalation import EscalationLevel, EscalationStatus
from app.services.call_customer_repository import CallCustomerRepository
from app.services.conversation_repository import ConversationRepository
from app.services.escalation_repository import EscalationRepository

# What the "high escalation" filter matches, whatever the escalation's status.
HIGH_ESCALATION_LEVELS = frozenset({EscalationLevel.HIGH, EscalationLevel.CRITICAL})


@dataclass(frozen=True)
class CallListFilters:
    """Every filter is optional; set ones must all match.

    Date bounds are epoch seconds, from inclusive and to exclusive, so a
    client sends local midnights for a day range.
    """

    # Empty means any status.
    statuses: frozenset[ConversationStatus] = frozenset()
    high_escalation: bool = False
    # Case-insensitive part of the customer name or vehicle registration.
    customer: str | None = None
    # Digits that appear in the caller's number, in order.
    phone: str | None = None
    started_from: float | None = None
    started_to: float | None = None
    resolved_from: float | None = None
    resolved_to: float | None = None

    @property
    def customer_text(self) -> str | None:
        text = (self.customer or "").strip()
        return text or None

    @property
    def phone_digits(self) -> str | None:
        return re.sub(r"\D", "", self.phone or "") or None


@dataclass(frozen=True)
class CallListItem:
    call_id: str
    status: ConversationStatus
    start_time: float
    end_time: float | None
    utterance_count: int
    caller_number: str | None = None
    customer_name: str | None = None
    vehicle_registration: str | None = None
    escalation_level: EscalationLevel | None = None
    escalation_status: EscalationStatus | None = None
    # When the last of the call's complaints was resolved; None while any is
    # still open, or when the call raised no complaints.
    complaints_resolved_at: float | None = None


@dataclass(frozen=True)
class CallListPage:
    items: tuple[CallListItem, ...]
    # Calls matching the filters, across all pages.
    total: int


class CallListingQuery(ABC):
    @abstractmethod
    def search(self, filters: CallListFilters, limit: int, offset: int) -> CallListPage:
        """Matching calls, newest-created first."""
        raise NotImplementedError


def complaints_resolved_at(
    records: Iterable[ComplaintLifecycleRecord],
    events: Mapping[str, tuple[ComplaintLifecycleEvent, ...]],
) -> float | None:
    """When the call's complaints were all resolved: the latest time any of
    them was marked resolved. None if any is still open, or there are none."""
    times = []
    for record in records:
        if record.status is not ComplaintLifecycleStatus.RESOLVED:
            return None
        resolved = [
            event.at
            for event in events.get(record.complaint_id, ())
            if event.status is ComplaintLifecycleStatus.RESOLVED
        ]
        times.append(max(resolved) if resolved else record.last_updated_at)
    return max(times, default=None)


def _in_range(value: float | None, start: float | None, end: float | None) -> bool:
    if start is None and end is None:
        return True
    if value is None:
        return False
    return (start is None or value >= start) and (end is None or value < end)


def _contains(value: str | None, text: str) -> bool:
    return value is not None and text in value.casefold()


def matches(item: CallListItem, filters: CallListFilters) -> bool:
    if filters.statuses and item.status not in filters.statuses:
        return False
    if filters.high_escalation and item.escalation_level not in HIGH_ESCALATION_LEVELS:
        return False
    customer = filters.customer_text
    if customer is not None:
        text = customer.casefold()
        registration = (item.vehicle_registration or "").replace(" ", "").casefold()
        if not (_contains(item.customer_name, text) or text.replace(" ", "") in registration):
            return False
    digits = filters.phone_digits
    if digits is not None and (item.caller_number is None or digits not in item.caller_number):
        return False
    return _in_range(item.start_time, filters.started_from, filters.started_to) and _in_range(
        item.complaints_resolved_at, filters.resolved_from, filters.resolved_to
    )


class InMemoryCallListingQuery(CallListingQuery):
    """Filters in Python over the in-memory repositories."""

    def __init__(
        self,
        conversations: ConversationRepository,
        call_customers: CallCustomerRepository,
        escalations: EscalationRepository,
        complaints: ComplaintLifecycleRepository,
    ) -> None:
        self._conversations = conversations
        self._call_customers = call_customers
        self._escalations = escalations
        self._complaints = complaints

    def search(self, filters: CallListFilters, limit: int, offset: int) -> CallListPage:
        conversations = self._conversations.list_page(self._conversations.count(), 0)
        escalations = self._escalations.get_many(c.call_id for c in conversations)
        matching = [
            item
            for item in (self._item(c, escalations.get(c.call_id)) for c in conversations)
            if matches(item, filters)
        ]
        return CallListPage(tuple(matching[offset : offset + limit]), len(matching))

    def _item(self, conversation, escalation) -> CallListItem:
        link = self._call_customers.get(conversation.call_id)
        records = self._complaints.list_for_call(conversation.call_id)
        events = self._complaints.list_events(r.complaint_id for r in records)
        return CallListItem(
            call_id=conversation.call_id,
            status=conversation.status,
            start_time=conversation.start_time,
            end_time=conversation.end_time,
            utterance_count=conversation.utterance_count,
            caller_number=None if link is None else link.caller_number,
            customer_name=None if link is None else link.customer_name,
            vehicle_registration=None if link is None else link.vehicle_registration,
            escalation_level=None if escalation is None else escalation.level,
            escalation_status=None if escalation is None else escalation.status,
            complaints_resolved_at=complaints_resolved_at(records, events),
        )
