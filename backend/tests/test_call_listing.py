"""The browsable call list: filters, the complaints-resolved date and paging.
Every listing test runs against both the in-memory query and the SQL one
(on SQLite, like test_postgresql_persistence), so the two stay in step."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.pool import StaticPool

from app.domain.call_customer import CallCustomerLink
from app.domain.complaint_lifecycle import (
    ComplaintLifecycleEvent,
    ComplaintLifecycleRecord,
    ComplaintLifecycleStatus,
)
from app.domain.complaint_lifecycle_repository import InMemoryComplaintLifecycleRepository
from app.domain.conversation import Conversation, ConversationStatus
from app.domain.utterance import SpeakerRole, Utterance
from app.domain.escalation import (
    Escalation,
    EscalationLevel,
    EscalationSignal,
    EscalationSignalType,
    EscalationStatus,
)
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import build_session_factory
from app.infrastructure.database.models import ConversationModel
from app.infrastructure.database.repositories.call_customer_repository import (
    PostgresCallCustomerRepository,
)
from app.infrastructure.database.repositories.call_listing_query import (
    PostgresCallListingQuery,
)
from app.infrastructure.database.repositories.complaint_lifecycle_repository import (
    PostgresComplaintLifecycleRepository,
)
from app.infrastructure.database.repositories.conversation_repository import (
    PostgresConversationRepository,
)
from app.infrastructure.database.repositories.escalation_repository import (
    PostgresEscalationRepository,
)
from app.services.call_customer_repository import InMemoryCallCustomerRepository
from app.services.call_listing import (
    CallListFilters,
    InMemoryCallListingQuery,
    complaints_resolved_at,
)
from app.services.escalation_repository import InMemoryEscalationRepository
from app.services.in_memory_conversation_repository import InMemoryConversationRepository

RESOLVED = ComplaintLifecycleStatus.RESOLVED
RAISED = ComplaintLifecycleStatus.RAISED
DAY = 86_400.0


def _record(complaint_id, call_id, status, updated_at=10.0):
    return ComplaintLifecycleRecord(
        complaint_id=complaint_id,
        call_id=call_id,
        category="Communication",
        status=status,
        first_detected_at=1.0,
        last_updated_at=updated_at,
    )


def _event(complaint_id, status, at):
    return ComplaintLifecycleEvent(complaint_id, status, at, actor="system")


def test_resolved_at_is_the_last_resolution_once_every_complaint_is_resolved():
    records = [_record("a", "c", RESOLVED), _record("b", "c", RESOLVED, updated_at=99.0)]
    events = {
        "a": (_event("a", RAISED, 1.0), _event("a", RESOLVED, 20.0)),
        # Resolved, reopened for follow-up and resolved again: the last one counts.
        "b": (_event("b", RESOLVED, 5.0), _event("b", RESOLVED, 30.0)),
    }

    assert complaints_resolved_at(records, events) == 30.0


def test_resolved_at_is_none_while_a_complaint_is_open_or_without_complaints():
    records = [_record("a", "c", RESOLVED), _record("b", "c", RAISED)]

    assert complaints_resolved_at(records, {"a": (_event("a", RESOLVED, 20.0),)}) is None
    assert complaints_resolved_at([], {}) is None


def test_resolved_at_falls_back_to_the_record_without_a_resolution_event():
    assert complaints_resolved_at([_record("a", "c", RESOLVED, updated_at=42.0)], {}) == 42.0


class _Stores:
    def __init__(self, session_factory=None):
        self._session_factory = session_factory
        if session_factory is None:
            self.conversations = InMemoryConversationRepository()
            self.customers = InMemoryCallCustomerRepository()
            self.escalations = InMemoryEscalationRepository()
            self.complaints = InMemoryComplaintLifecycleRepository()
            self.query = InMemoryCallListingQuery(
                self.conversations, self.customers, self.escalations, self.complaints
            )
        else:
            self.conversations = PostgresConversationRepository(session_factory)
            self.customers = PostgresCallCustomerRepository(session_factory)
            self.escalations = PostgresEscalationRepository(session_factory)
            self.complaints = PostgresComplaintLifecycleRepository(session_factory)
            self.query = PostgresCallListingQuery(session_factory)
        self._created = datetime(2026, 1, 1)

    def call(self, call_id, start_time, completed=False):
        conversation = Conversation(call_id=call_id, start_time=start_time)
        if completed:
            conversation.complete(start_time + 60)
        self.conversations.add(conversation)
        if self._session_factory is not None:
            # SQLite's creation timestamps tie within a second; set them apart.
            self._created += timedelta(minutes=1)
            with self._session_factory() as session, session.begin():
                session.execute(
                    update(ConversationModel)
                    .where(ConversationModel.call_id == call_id)
                    .values(created_at=self._created)
                )

    def escalate(self, call_id, level, status=EscalationStatus.OPEN):
        resolved = status is EscalationStatus.RESOLVED
        self.escalations.save(
            Escalation(
                call_id=call_id,
                level=level,
                signals=(
                    EscalationSignal(EscalationSignalType.OTHER, level, "Escalated in a test."),
                ),
                status=status,
                first_detected_at=1.0,
                updated_at=1.0,
                resolved_by="sup" if resolved else None,
                resolved_at=2.0 if resolved else None,
            )
        )

    def resolve_complaint(self, call_id, at):
        complaint_id = f"{call_id}:x"
        self.complaints.save(_record(complaint_id, call_id, RESOLVED, updated_at=at))
        self.complaints.add_event(_event(complaint_id, RESOLVED, at))

    def ids(self, **filters):
        page = self.query.search(CallListFilters(**filters), 50, 0)
        return [item.call_id for item in page.items]


@pytest.fixture(params=["memory", "sql"])
def stores(request):
    if request.param == "memory":
        s = _Stores()
    else:
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        request.addfinalizer(engine.dispose)
        s = _Stores(build_session_factory(engine))
    s.call("old", 1 * DAY, completed=True)
    s.call("mid", 5 * DAY, completed=True)
    s.call("new", 9 * DAY)
    s.call("quiet", 3 * DAY)  # no customer, escalation or complaints
    s.customers.save(
        CallCustomerLink(
            "old",
            caller_number="+919845000001",
            customer_id="C-1",
            customer_name="Asha Raman",
            vehicle_registration="TN09AB1234",
        )
    )
    s.customers.save(CallCustomerLink("new", caller_number="+919845000002"))
    s.escalate("old", EscalationLevel.CRITICAL, EscalationStatus.RESOLVED)
    s.escalate("mid", EscalationLevel.WATCH)
    s.escalate("new", EscalationLevel.HIGH)
    s.resolve_complaint("old", 2 * DAY)
    s.resolve_complaint("mid", 6 * DAY)
    # One complaint resolved, one still open: the call is not resolved.
    s.resolve_complaint("new", 3 * DAY)
    s.complaints.save(_record("new:open", "new", RAISED))
    return s


def test_newest_first_with_paging_and_total(stores):
    page = stores.query.search(CallListFilters(), limit=2, offset=1)

    assert [item.call_id for item in page.items] == ["new", "mid"]
    assert page.total == 4


def test_utterances_are_counted_and_missing_details_are_empty(stores):
    conversation = stores.conversations.get("new")
    for n in range(2):
        conversation.add_utterance(
            Utterance(f"u{n}", "Hello", SpeakerRole.CUSTOMER, ("en",), float(n), n + 0.5)
        )
    stores.conversations.save(conversation)  # keeps its creation time
    items = {item.call_id: item for item in stores.query.search(CallListFilters(), 10, 0).items}

    assert items["new"].utterance_count == 2
    assert items["mid"].utterance_count == 0
    assert items["quiet"].customer_name is None
    assert items["quiet"].escalation_level is None
    assert items["new"].complaints_resolved_at is None


def test_items_carry_customer_escalation_and_resolution(stores):
    (item,) = stores.query.search(CallListFilters(customer="asha"), 10, 0).items

    assert item.customer_name == "Asha Raman"
    assert item.vehicle_registration == "TN09AB1234"
    assert item.caller_number == "+919845000001"
    assert item.escalation_level is EscalationLevel.CRITICAL
    assert item.complaints_resolved_at == 2 * DAY


def test_status_and_high_escalation_filters(stores):
    assert stores.ids(statuses=frozenset({ConversationStatus.ACTIVE})) == ["quiet", "new"]
    assert stores.ids(statuses=frozenset(ConversationStatus)) == ["quiet", "new", "mid", "old"]
    # High or critical, whether or not the escalation is resolved.
    assert stores.ids(high_escalation=True) == ["new", "old"]
    completed = frozenset({ConversationStatus.COMPLETED})
    assert stores.ids(high_escalation=True, statuses=completed) == ["old"]


@pytest.mark.parametrize(
    "customer, expected",
    [("ASHA", ["old"]), ("tn09 ab", ["old"]), ("  ", ["quiet", "new", "mid", "old"]), ("zed", [])],
)
def test_customer_search_matches_name_or_registration(stores, customer, expected):
    assert stores.ids(customer=customer) == expected


def test_phone_search_matches_digits_only(stores):
    assert stores.ids(phone="98450-00002") == ["new"]
    assert stores.ids(phone="9845") == ["new", "old"]
    assert stores.ids(phone="abc") == ["quiet", "new", "mid", "old"]  # no digits: no filter


def test_date_ranges_include_from_and_exclude_to(stores):
    assert stores.ids(started_from=5 * DAY, started_to=9 * DAY) == ["mid"]
    assert stores.ids(started_from=5 * DAY) == ["new", "mid"]
    assert stores.ids(started_to=5 * DAY) == ["quiet", "old"]
    # Calls without a resolution date never match a resolved range.
    assert stores.ids(resolved_to=4 * DAY) == ["old"]
    assert stores.ids(resolved_from=2 * DAY, resolved_to=7 * DAY) == ["mid", "old"]
