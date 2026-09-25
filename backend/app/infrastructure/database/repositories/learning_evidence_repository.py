from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.learning_evidence import EvidenceType, LearningComponent, LearningEvidence
from app.domain.learning_evidence_repository import LearningEvidenceRepository
from app.infrastructure.database.models import LearningEvidenceModel


def _to_domain(model: LearningEvidenceModel) -> LearningEvidence:
    return LearningEvidence(
        evidence_id=model.evidence_id,
        call_id=model.call_id,
        evidence_type=EvidenceType(model.evidence_type),
        component=LearningComponent(model.component),
        description=model.description,
        expected_value=model.expected_value,
        actual_value=model.actual_value,
        human_correction=model.human_correction,
        created_at=model.created_at,
    )


def _to_model(evidence: LearningEvidence) -> LearningEvidenceModel:
    return LearningEvidenceModel(
        evidence_id=evidence.evidence_id,
        call_id=evidence.call_id,
        evidence_type=evidence.evidence_type.value,
        component=evidence.component.value,
        description=evidence.description,
        expected_value=evidence.expected_value,
        actual_value=evidence.actual_value,
        human_correction=evidence.human_correction,
        created_at=evidence.created_at,
    )


class PostgresLearningEvidenceRepository(LearningEvidenceRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, evidence: LearningEvidence) -> None:
        with self._session_factory() as session, session.begin():
            existing = session.get(LearningEvidenceModel, evidence.evidence_id)
            if existing is not None:
                session.delete(existing)
                session.flush()
            session.add(_to_model(evidence))

    def get(self, evidence_id: str) -> LearningEvidence | None:
        with self._session_factory() as session:
            model = session.get(LearningEvidenceModel, evidence_id)
            return None if model is None else _to_domain(model)

    def list_all(self) -> tuple[LearningEvidence, ...]:
        with self._session_factory() as session:
            models = session.scalars(select(LearningEvidenceModel)).all()
            return tuple(_to_domain(model) for model in models)