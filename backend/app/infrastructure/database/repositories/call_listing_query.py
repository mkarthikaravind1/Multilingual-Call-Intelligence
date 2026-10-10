from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.complaint_lifecycle import ComplaintLifecycleStatus
from app.domain.conversation import CallDirection, ConversationStatus
from app.domain.escalation import EscalationLevel, EscalationStatus
from app.infrastructure.database.models import (
    CallCustomerModel,
    ComplaintLifecycleEventModel,
    ComplaintLifecycleRecordModel,
    ConversationModel,
    EscalationModel,
    LocationModel,
    UserModel,
    UtteranceModel,
)
from app.services.call_listing import (
    HIGH_ESCALATION_LEVELS,
    CallListFilters,
    CallListingQuery,
    CallListItem,
    CallListPage,
)

_RESOLVED = ComplaintLifecycleStatus.RESOLVED.value


def _like_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _complaints_resolved_at():
    """Per call whose complaints are all resolved: when the last of them was
    (its latest resolved event; last_updated_at if it has none). Mirrors
    app.services.call_listing.complaints_resolved_at."""
    record = ComplaintLifecycleRecordModel
    event = ComplaintLifecycleEventModel
    resolved_events = (
        select(event.complaint_id, func.max(event.at).label("at"))
        .where(event.status == _RESOLVED)
        .group_by(event.complaint_id)
        .subquery()
    )
    return (
        select(
            record.call_id.label("call_id"),
            func.max(func.coalesce(resolved_events.c.at, record.last_updated_at)).label(
                "resolved_at"
            ),
        )
        .outerjoin(resolved_events, resolved_events.c.complaint_id == record.complaint_id)
        .group_by(record.call_id)
        .having(func.sum(case((record.status != _RESOLVED, 1), else_=0)) == 0)
        .subquery()
    )


def _utterance_counts():
    return (
        select(UtteranceModel.call_id.label("call_id"), func.count().label("count"))
        .group_by(UtteranceModel.call_id)
        .subquery()
    )


def _apply_range(query: Select, column, start: float | None, end: float | None) -> Select:
    if start is not None:
        query = query.where(column >= start)
    if end is not None:
        query = query.where(column < end)
    return query


class PostgresCallListingQuery(CallListingQuery):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def search(self, filters: CallListFilters, limit: int, offset: int) -> CallListPage:
        conversation = ConversationModel
        customer = CallCustomerModel
        escalation = EscalationModel
        location = LocationModel
        executive = UserModel
        resolved = _complaints_resolved_at()
        utterances = _utterance_counts()

        query = (
            select(
                conversation.call_id,
                conversation.status,
                conversation.start_time,
                conversation.end_time,
                func.coalesce(utterances.c.count, 0).label("utterance_count"),
                customer.caller_number,
                customer.customer_name,
                customer.vehicle_registration,
                escalation.level,
                escalation.status.label("escalation_status"),
                resolved.c.resolved_at,
                conversation.direction,
                conversation.location_id,
                location.name.label("location_name"),
                conversation.executive_user_id,
                func.coalesce(executive.display_name, executive.email).label("executive_name"),
                conversation.holds,
            )
            .outerjoin(location, location.location_id == conversation.location_id)
            .outerjoin(executive, executive.user_id == conversation.executive_user_id)
            .outerjoin(customer, customer.call_id == conversation.call_id)
            .outerjoin(escalation, escalation.call_id == conversation.call_id)
            .outerjoin(resolved, resolved.c.call_id == conversation.call_id)
            .outerjoin(utterances, utterances.c.call_id == conversation.call_id)
        )

        if filters.statuses:
            query = query.where(conversation.status.in_([s.value for s in filters.statuses]))
        if filters.high_escalation:
            query = query.where(
                escalation.level.in_([level.value for level in HIGH_ESCALATION_LEVELS])
            )
        text = filters.customer_text
        if text is not None:
            query = query.where(
                or_(
                    customer.customer_name.ilike(_like_pattern(text), escape="\\"),
                    func.replace(customer.vehicle_registration, " ", "").ilike(
                        _like_pattern(text.replace(" ", "")), escape="\\"
                    ),
                )
            )
        digits = filters.phone_digits
        if digits is not None:
            query = query.where(customer.caller_number.like(_like_pattern(digits)))
        if filters.location_id is not None:
            query = query.where(conversation.location_id == filters.location_id)
        if filters.executive_user_id is not None:
            query = query.where(conversation.executive_user_id == filters.executive_user_id)
        if filters.direction is not None:
            query = query.where(conversation.direction == filters.direction.value)
        query = _apply_range(
            query, conversation.start_time, filters.started_from, filters.started_to
        )
        query = _apply_range(
            query, resolved.c.resolved_at, filters.resolved_from, filters.resolved_to
        )

        with self._session_factory() as session:
            total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
            rows = session.execute(
                query.order_by(conversation.created_at.desc(), conversation.call_id)
                .limit(limit)
                .offset(offset)
            ).all()

        return CallListPage(items=tuple(_item(row) for row in rows), total=total)

    def active_calls(self, limit: int) -> tuple[CallListItem, ...]:
        # Read every few seconds by the live view, so it does only what
        # that needs: the calls in progress (found by the status index),
        # with each one's lines counted through the utterance call index.
        # search() counts the lines of every call ever made, and works out
        # when complaints were resolved, before it filters.
        conversation = ConversationModel
        customer = CallCustomerModel
        escalation = EscalationModel
        location = LocationModel
        executive = UserModel
        utterance_count = (
            select(func.count())
            .where(UtteranceModel.call_id == conversation.call_id)
            .correlate(conversation)
            .scalar_subquery()
        )
        query = (
            select(
                conversation.call_id,
                conversation.status,
                conversation.start_time,
                conversation.end_time,
                utterance_count.label("utterance_count"),
                customer.caller_number,
                customer.customer_name,
                customer.vehicle_registration,
                escalation.level,
                escalation.status.label("escalation_status"),
                conversation.direction,
                conversation.location_id,
                location.name.label("location_name"),
                conversation.executive_user_id,
                func.coalesce(executive.display_name, executive.email).label("executive_name"),
                conversation.holds,
            )
            .outerjoin(location, location.location_id == conversation.location_id)
            .outerjoin(executive, executive.user_id == conversation.executive_user_id)
            .outerjoin(customer, customer.call_id == conversation.call_id)
            .outerjoin(escalation, escalation.call_id == conversation.call_id)
            .where(conversation.status == ConversationStatus.ACTIVE.value)
            .order_by(conversation.created_at.desc(), conversation.call_id)
            .limit(limit)
        )
        with self._session_factory() as session:
            rows = session.execute(query).all()
        return tuple(_item(row) for row in rows)


def _item(row) -> CallListItem:
    return CallListItem(
        call_id=row.call_id,
        status=ConversationStatus(row.status),
        start_time=row.start_time,
        end_time=row.end_time,
        utterance_count=row.utterance_count,
        caller_number=row.caller_number,
        customer_name=row.customer_name,
        vehicle_registration=row.vehicle_registration,
        escalation_level=None if row.level is None else EscalationLevel(row.level),
        escalation_status=(
            None if row.escalation_status is None else EscalationStatus(row.escalation_status)
        ),
        # Not part of the live view's read.
        complaints_resolved_at=getattr(row, "resolved_at", None),
        direction=None if row.direction is None else CallDirection(row.direction),
        location_id=row.location_id,
        location_name=row.location_name,
        executive_user_id=row.executive_user_id,
        executive_name=row.executive_name,
        # The last hold has not ended.
        on_hold=bool(row.holds) and row.holds[-1].get("ended_at") is None,
    )
