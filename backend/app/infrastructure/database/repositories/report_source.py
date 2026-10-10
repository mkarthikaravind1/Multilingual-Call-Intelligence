from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.sentiment.provider import SentimentLabel
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import CallDirection
from app.domain.escalation import EscalationLevel
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


class PostgresReportSource(ReportSource):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def calls(self, filters: ReportFilters, limit: int) -> tuple[ReportCall, ...]:
        conversation = ConversationModel
        summary = PostCallSummaryModel
        location = LocationModel
        executive = UserModel
        coverage = ComplaintCoverageModel
        tracked = ComplaintLifecycleRecordModel
        customer = CallCustomerModel
        escalation = EscalationModel

        query = (
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
            )
            .outerjoin(customer, customer.call_id == conversation.call_id)
            .outerjoin(escalation, escalation.call_id == conversation.call_id)
            .outerjoin(summary, summary.call_id == conversation.call_id)
            .outerjoin(location, location.location_id == conversation.location_id)
            .outerjoin(executive, executive.user_id == conversation.executive_user_id)
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
            query = query.where(summary.sentiment_label == filters.sentiment.value)
        query = query.order_by(conversation.start_time, conversation.call_id).limit(limit)

        with self._session_factory() as session:
            rows = session.execute(query).all()
            # The categories raised on those calls, in the order detected.
            page = query.subquery()
            raised = session.execute(
                select(coverage.call_id, coverage.category, coverage.status)
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
                select(
                    UtteranceModel.call_id,
                    UtteranceModel.transcript,
                    UtteranceModel.complaint_categories,
                )
                .join(page, page.c.call_id == UtteranceModel.call_id)
                .where(UtteranceModel.complaint_categories.is_not(None))
                .order_by(UtteranceModel.start_time, UtteranceModel.utterance_id)
            ).all():
                spoken[call_id].append((transcript, categories))

            outcomes: dict[str, dict[str, int]] = defaultdict(dict)
            for call_id, choice, count in session.execute(
                select(
                    QuestionOutcomeModel.call_id, QuestionOutcomeModel.outcome, func.count()
                )
                .join(page, page.c.call_id == QuestionOutcomeModel.call_id)
                .group_by(QuestionOutcomeModel.call_id, QuestionOutcomeModel.outcome)
            ).all():
                outcomes[call_id][choice] = count

        by_call: dict[str, list[tuple[str, str, bool]]] = defaultdict(list)
        for call_id, category, status in raised:
            by_call[call_id].append(
                (category, current.get((call_id, category), status), status != _DETECTED)
            )

        calls = []
        for row in rows:
            descriptions = {
                c.get("category"): c.get("description") for c in row.summary_complaints or []
            }
            quotes = first_quotes(spoken.get(row.call_id, ()))
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
                        )
                        for category, status, probed in by_call.get(row.call_id, ())
                    ),
                    customer_key=customer_key(row.customer_id, row.caller_number),
                    questions_accepted=outcomes[row.call_id].get("accepted", 0),
                    questions_skipped=outcomes[row.call_id].get("skipped", 0),
                    escalation_level=(
                        None
                        if row.escalation_level is None
                        else EscalationLevel(row.escalation_level)
                    ),
                )
            )
        return tuple(calls)
