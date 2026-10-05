from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.ai.sentiment.provider import SentimentLabel, SentimentResult
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.post_call_summary import ComplaintSummary, PostCallSummary
from app.domain.service_estimate import call_estimate_from_json, call_estimate_to_json
from app.infrastructure.database.models import PostCallSummaryModel
from app.services.post_call_summary_repository import PostCallSummaryRepository


def _to_model(summary: PostCallSummary) -> PostCallSummaryModel:
    return PostCallSummaryModel(
        call_id=summary.call_id,
        overall_summary=summary.overall_summary,
        customer_summary=summary.customer_summary,
        languages=list(summary.languages),
        sentiment_label=summary.sentiment.label.value,
        sentiment_confidence=summary.sentiment.confidence,
        sentiment_evidence=summary.sentiment.evidence,
        complaints=[
            {
                "category": complaint.category,
                "description": complaint.description,
                "status": complaint.status.value,
                "evidence": complaint.evidence,
                "confidence": complaint.confidence,
            }
            for complaint in summary.complaints
        ],
        unresolved_issues=list(summary.unresolved_issues),
        actions_promised=list(summary.actions_promised),
        follow_up_required=summary.follow_up_required,
        service_estimate=(
            None
            if summary.service_estimate is None
            else call_estimate_to_json(summary.service_estimate)
        ),
    )


def _to_domain(model: PostCallSummaryModel) -> PostCallSummary:
    return PostCallSummary(
        call_id=model.call_id,
        overall_summary=model.overall_summary,
        languages=tuple(model.languages),
        sentiment=SentimentResult(
            label=SentimentLabel(model.sentiment_label),
            confidence=model.sentiment_confidence,
            evidence=model.sentiment_evidence,
        ),
        complaints=tuple(
            ComplaintSummary(
                category=complaint["category"],
                description=complaint["description"],
                status=ComplaintCoverageStatus(complaint["status"]),
                evidence=complaint["evidence"],
                confidence=complaint["confidence"],
            )
            for complaint in model.complaints
        ),
        unresolved_issues=tuple(model.unresolved_issues),
        actions_promised=tuple(model.actions_promised),
        follow_up_required=model.follow_up_required,
        customer_summary=model.customer_summary,
        service_estimate=(
            None
            if model.service_estimate is None
            else call_estimate_from_json(model.service_estimate)
        ),
    )


class PostgresPostCallSummaryRepository(PostCallSummaryRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, call_id: str) -> PostCallSummary | None:
        with self._session_factory() as session:
            model = session.get(PostCallSummaryModel, call_id)
            return None if model is None else _to_domain(model)

    def add_if_absent(self, summary: PostCallSummary) -> PostCallSummary:
        try:
            with self._session_factory() as session, session.begin():
                existing = session.get(PostCallSummaryModel, summary.call_id)
                if existing is not None:
                    return _to_domain(existing)
                session.add(_to_model(summary))
            return summary
        except IntegrityError:
            # Another process inserted the same call_id between our read and write.
            stored = self.get(summary.call_id)
            if stored is None:
                raise
            return stored
