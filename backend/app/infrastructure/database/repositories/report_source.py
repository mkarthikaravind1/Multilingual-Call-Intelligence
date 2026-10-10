from collections import defaultdict

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.sentiment.provider import SentimentLabel
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import CallDirection
from app.domain.escalation import EscalationLevel, EscalationStatus
from app.infrastructure.database.models import (
    CallCustomerModel,
    ComplaintCoverageModel,
    EscalationModel,
    ComplaintLifecycleRecordModel,
    ConversationModel,
    LocationModel,
    PostCallSummaryModel,
    QuestionOutcomeModel,
    UserModel,
    UtteranceModel,
)
from app.infrastructure.database.repositories.conversation_repository import holds_from_json
from app.services.reporting import (
    ReportCall,
    ReportComplaint,
    ReportFilters,
    ReportSource,
    customer_key,
    first_quotes,
)

_NOT_RAISED = ComplaintCoverageStatus.NOT_RAISED.value
_DETECTED = ComplaintCoverageStatus.DETECTED.value
_RESOLVED_ESCALATION = EscalationStatus.RESOLVED.value


class PostgresReportSource(ReportSource):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def calls(self, filters: ReportFilters, limit: int) -> tuple[ReportCall, ...]:
        conversation = ConversationModel
        query = (
            _calls_query()
            .where(conversation.start_time >= filters.started_from)
            .where(conversation.start_time < filters.started_to)
        )
        if filters.location_id is not None:
            query = query.where(conversation.location_id == filters.location_id)
        if filters.executive_user_id is not None:
            query = query.where(conversation.executive_user_id == filters.executive_user_id)
        if filters.direction is not None:
            query = query.where(conversation.direction == filters.direction.value)
        if filters.sentiment is not None:
            query = query.where(PostCallSummaryModel.sentiment_label == filters.sentiment.value)
        query = query.order_by(conversation.start_time, conversation.call_id).limit(limit)
        return self._load(query)

    def call(self, call_id: str) -> ReportCall | None:
        found = self._load(_calls_query().where(ConversationModel.call_id == call_id))
        return found[0] if found else None

    def _load(self, query: Select) -> tuple[ReportCall, ...]:
        """The calls the query selects, each with what the stores beside
        the call hold about it (one read per store, whatever the number of
        calls)."""
        coverage = ComplaintCoverageModel
        tracked = ComplaintLifecycleRecordModel
        utterance = UtteranceModel
        with self._session_factory() as session:
            rows = session.execute(query).all()
            page = query.subquery()
            # The categories raised on those calls, in the order detected.
            raised = session.execute(
                select(coverage.call_id, coverage.category, coverage.status, coverage.confidence)
                .join(page, page.c.call_id == coverage.call_id)
                .where(coverage.status != _NOT_RAISED)
                .order_by(coverage.id)
            ).all()
            # Where each of those complaints stands now, when it is tracked.
            current = {
                (call_id, category): status
                for call_id, category, status in session.execute(
                    select(tracked.call_id, tracked.category, tracked.status).join(
                        page, page.c.call_id == tracked.call_id
                    )
                ).all()
            }

            # The lines that raise a complaint, in the order spoken: the
            # customer's own words for each category.
            spoken: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
            for call_id, transcript, categories in session.execute(
                select(utterance.call_id, utterance.transcript, utterance.complaint_categories)
                .join(page, page.c.call_id == utterance.call_id)
                .where(utterance.complaint_categories.is_not(None))
                .order_by(utterance.start_time, utterance.utterance_id)
            ).all():
                spoken[call_id].append((transcript, categories))

            # The tone of each call's first and last rated line: whether
            # the customer left better or worse than they began.
            rated = (
                select(
                    utterance.call_id.label("call_id"),
                    utterance.sentiment.label("sentiment"),
                    func.row_number()
                    .over(
                        partition_by=utterance.call_id,
                        order_by=(utterance.start_time, utterance.utterance_id),
                    )
                    .label("from_start"),
                    func.row_number()
                    .over(
                        partition_by=utterance.call_id,
                        order_by=(utterance.start_time.desc(), utterance.utterance_id.desc()),
                    )
                    .label("from_end"),
                )
                .join(page, page.c.call_id == utterance.call_id)
                .where(utterance.sentiment.is_not(None))
                .subquery()
            )
            tone_start: dict[str, SentimentLabel] = {}
            tone_end: dict[str, SentimentLabel] = {}
            for call_id, sentiment, from_start, from_end in session.execute(
                select(rated.c.call_id, rated.c.sentiment, rated.c.from_start, rated.c.from_end)
                .where((rated.c.from_start == 1) | (rated.c.from_end == 1))
            ).all():
                if from_start == 1:
                    tone_start[call_id] = SentimentLabel(sentiment)
                if from_end == 1:
                    tone_end[call_id] = SentimentLabel(sentiment)

            # Suggested questions accepted and skipped, per complaint category.
            outcomes: dict[str, dict[tuple[str, str], int]] = defaultdict(dict)
            for call_id, category, choice, count in session.execute(
                select(
                    QuestionOutcomeModel.call_id,
                    QuestionOutcomeModel.target_category,
                    QuestionOutcomeModel.outcome,
                    func.count(),
                )
                .join(page, page.c.call_id == QuestionOutcomeModel.call_id)
                .group_by(
                    QuestionOutcomeModel.call_id,
                    QuestionOutcomeModel.target_category,
                    QuestionOutcomeModel.outcome,
                )
            ).all():
                outcomes[call_id][category, choice] = count

        by_call: dict[str, list[tuple[str, str, bool, float | None]]] = defaultdict(list)
        for call_id, category, status, confidence in raised:
            by_call[call_id].append(
                (
                    category,
                    current.get((call_id, category), status),
                    status != _DETECTED,
                    confidence,
                )
            )

        calls = []
        for row in rows:
            descriptions = {
                c.get("category"): c.get("description") for c in row.summary_complaints or []
            }
            quotes = first_quotes(spoken.get(row.call_id, ()))
            chosen = outcomes[row.call_id]
            calls.append(
                ReportCall(
                    call_id=row.call_id,
                    start_time=row.start_time,
                    direction=None if row.direction is None else CallDirection(row.direction),
                    location_id=row.location_id,
                    location_name=row.location_name,
                    executive_user_id=row.executive_user_id,
                    executive_name=row.executive_name,
                    sentiment=(
                        None
                        if row.sentiment_label is None
                        else SentimentLabel(row.sentiment_label)
                    ),
                    complaints=tuple(
                        ReportComplaint(
                            category,
                            status,
                            descriptions.get(category),
                            probed,
                            quotes.get(category),
                            confidence=confidence,
                            questions_accepted=chosen.get((category, "accepted"), 0),
                            questions_skipped=chosen.get((category, "skipped"), 0),
                        )
                        for category, status, probed, confidence in by_call.get(row.call_id, ())
                    ),
                    customer_key=customer_key(row.customer_id, row.caller_number),
                    questions_accepted=sum(
                        count for (_, choice), count in chosen.items() if choice == "accepted"
                    ),
                    questions_skipped=sum(
                        count for (_, choice), count in chosen.items() if choice == "skipped"
                    ),
                    escalation_level=(
                        None
                        if row.escalation_level is None
                        else EscalationLevel(row.escalation_level)
                    ),
                    escalation_open=(
                        row.escalation_level is not None
                        and row.escalation_status != _RESOLVED_ESCALATION
                    ),
                    tone_start=tone_start.get(row.call_id),
                    tone_end=tone_end.get(row.call_id),
                    hold_seconds=sum(hold.seconds for hold in holds_from_json(row.holds)),
                )
            )
        return tuple(calls)


def _calls_query() -> Select:
    """Every call with what one row per call can carry; filtered, ordered
    and limited by the caller."""
    conversation = ConversationModel
    summary = PostCallSummaryModel
    location = LocationModel
    executive = UserModel
    customer = CallCustomerModel
    escalation = EscalationModel
    return (
        select(
            conversation.call_id,
            conversation.start_time,
            conversation.direction,
            conversation.location_id,
            location.name.label("location_name"),
            conversation.executive_user_id,
            func.coalesce(executive.display_name, executive.email).label("executive_name"),
            summary.sentiment_label,
            summary.complaints.label("summary_complaints"),
            customer.customer_id,
            customer.caller_number,
            escalation.level.label("escalation_level"),
            escalation.status.label("escalation_status"),
            conversation.holds,
        )
        .outerjoin(customer, customer.call_id == conversation.call_id)
        .outerjoin(escalation, escalation.call_id == conversation.call_id)
        .outerjoin(summary, summary.call_id == conversation.call_id)
        .outerjoin(location, location.location_id == conversation.location_id)
        .outerjoin(executive, executive.user_id == conversation.executive_user_id)
    )
