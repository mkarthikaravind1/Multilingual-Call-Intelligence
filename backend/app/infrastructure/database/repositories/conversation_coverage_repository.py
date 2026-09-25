from sqlalchemy.orm import Session, sessionmaker

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
    return coverage


class PostgresConversationCoverageRepository(ConversationCoverageRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, coverage: ConversationCoverage) -> None:
        with self._session_factory() as session, session.begin():
            existing = session.get(ConversationCoverageModel, coverage.call_id)
            if existing is not None:
                session.delete(existing)
                session.flush()

            model = ConversationCoverageModel(
                call_id=coverage.call_id,
                complaints=[
                    ComplaintCoverageModel(
                        call_id=coverage.call_id,
                        category=complaint.category,
                        status=complaint.status.value,
                    )
                    for complaint in coverage.complaints
                ],
            )
            session.add(model)

    def get(self, call_id: str) -> ConversationCoverage | None:
        with self._session_factory() as session:
            model = session.get(ConversationCoverageModel, call_id)
            return None if model is None else _to_domain(model)