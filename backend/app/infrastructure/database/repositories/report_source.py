from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.sentiment.provider import SentimentLabel
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import CallDirection
from app.infrastructure.database.models import (
    ComplaintCoverageModel,
    ComplaintLifecycleRecordModel,
    ConversationModel,
    LocationModel,
    PostCallSummaryModel,
    UserModel,
)
from app.services.reporting import ReportCall, ReportComplaint, ReportFilters, ReportSource

_NOT_RAISED = ComplaintCoverageStatus.NOT_RAISED.value


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
            )
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

        by_call: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for call_id, category, status in raised:
            by_call[call_id].append((category, current.get((call_id, category), status)))

        calls = []
        for row in rows:
            descriptions = {
                c.get("category"): c.get("description") for c in row.summary_complaints or []
            }
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
                        ReportComplaint(category, status, descriptions.get(category))
                        for category, status in by_call.get(row.call_id, ())
                    ),
                )
            )
        return tuple(calls)
