from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.domain.complaint_coverage import ComplaintCoverage, ComplaintCoverageStatus
from app.domain.conversation_coverage import ConversationCoverage
from app.infrastructure.database.models import (
    ComplaintCoverageModel,
    ConversationCoverageModel,
)
from app.services.conversation_coverage_repository import ConversationCoverageRepository


def _to_domain(model: ConversationCoverageModel) -> ConversationCoverage:
    coverage = ConversationCoverage(call_id=model.call_id)
    for complaint_model in model.complaints:
        complaint = coverage.add(complaint_model.category)
        # ComplaintCoverage's transition methods only allow forward moves, so
        # restore the persisted status directly instead of replaying transitions.
        complaint.status = ComplaintCoverageStatus(complaint_model.status)
        complaint.confidence = complaint_model.confidence
        complaint.detected_at = complaint_model.detected_at
    return coverage


class PostgresConversationCoverageRepository(ConversationCoverageRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, coverage: ConversationCoverage) -> None:
        with self._session_factory() as session, session.begin():
            model = session.get(ConversationCoverageModel, coverage.call_id)
            if model is None:
                model = ConversationCoverageModel(call_id=coverage.call_id)
                session.add(model)

            # Updated in place (saved on every analysis of a live call):
            # a complaint already stored keeps its row and gets its new
            # status; one no longer in the coverage is deleted.
            stored = {complaint.category: complaint for complaint in model.complaints}
            complaints = []
            for complaint in coverage.complaints:
                row = stored.get(complaint.category) or ComplaintCoverageModel(
                    call_id=coverage.call_id, category=complaint.category
                )
                row.status = complaint.status.value
                row.confidence = complaint.confidence
                row.detected_at = complaint.detected_at
                complaints.append(row)
            model.complaints = complaints

    def get(self, call_id: str) -> ConversationCoverage | None:
        with self._session_factory() as session:
            model = session.get(ConversationCoverageModel, call_id)
            return None if model is None else _to_domain(model)

    def get_many(self, call_ids: Iterable[str]) -> dict[str, ConversationCoverage]:
        ids = list(call_ids)
        if not ids:
            return {}
        with self._session_factory() as session:
            models = session.scalars(
                select(ConversationCoverageModel)
                .where(ConversationCoverageModel.call_id.in_(ids))
                .options(selectinload(ConversationCoverageModel.complaints))
            ).all()
            return {model.call_id: _to_domain(model) for model in models}