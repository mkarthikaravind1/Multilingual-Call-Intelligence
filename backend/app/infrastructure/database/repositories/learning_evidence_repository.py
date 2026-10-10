from collections.abc import Collection

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.learning_evidence import EvidenceType, LearningComponent, LearningEvidence
from app.domain.learning_evidence_repository import LearningEvidenceRepository
from app.infrastructure.database.models import LearningEvidenceModel
from app.infrastructure.database.repositories._saving import save_row


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
        save_row(self._session_factory, _to_model(evidence))

    def get(self, evidence_id: str) -> LearningEvidence | None:
        with self._session_factory() as session:
            model = session.get(LearningEvidenceModel, evidence_id)
            return None if model is None else _to_domain(model)

    def list_all(self) -> tuple[LearningEvidence, ...]:
        with self._session_factory() as session:
            models = session.scalars(select(LearningEvidenceModel)).all()
            return tuple(_to_domain(model) for model in models)

    def list_page(self, limit: int, offset: int = 0) -> tuple[LearningEvidence, ...]:
        with self._session_factory() as session:
            models = session.scalars(
                select(LearningEvidenceModel)
                .order_by(
                    LearningEvidenceModel.created_at.desc(),
                    LearningEvidenceModel.evidence_id.desc(),
                )
                .limit(limit)
                .offset(offset)
            ).all()
            return tuple(_to_domain(model) for model in models)

    def count(self) -> int:
        with self._session_factory() as session:
            return session.scalar(select(func.count()).select_from(LearningEvidenceModel)) or 0

    def list_judged(self) -> tuple[LearningEvidence, ...]:
        with self._session_factory() as session:
            models = session.scalars(
                select(LearningEvidenceModel).where(
                    or_(
                        LearningEvidenceModel.human_correction.is_not(None),
                        LearningEvidenceModel.expected_value.is_not(None),
                    )
                )
            ).all()
            return tuple(_to_domain(model) for model in models)

    def prediction_calls(self) -> dict[tuple[LearningComponent, str], int]:
        with self._session_factory() as session:
            rows = session.execute(
                select(
                    LearningEvidenceModel.component,
                    LearningEvidenceModel.actual_value,
                    func.count(distinct(LearningEvidenceModel.call_id)),
                )
                .where(
                    LearningEvidenceModel.evidence_type == EvidenceType.AI_PREDICTION.value,
                    LearningEvidenceModel.actual_value.is_not(None),
                )
                .group_by(LearningEvidenceModel.component, LearningEvidenceModel.actual_value)
            ).all()
        # Outputs that differ only in case or spacing are one output.
        calls: dict[tuple[LearningComponent, str], int] = {}
        for component, actual_value, call_count in rows:
            key = (LearningComponent(component), actual_value.strip().casefold())
            calls[key] = calls.get(key, 0) + call_count
        return calls

    def list_for_outputs(
        self, component: LearningComponent, actual_values: Collection[str]
    ) -> tuple[LearningEvidence, ...]:
        if not actual_values:
            return ()
        with self._session_factory() as session:
            models = session.scalars(
                select(LearningEvidenceModel).where(
                    LearningEvidenceModel.component == component.value,
                    LearningEvidenceModel.actual_value.in_(list(actual_values)),
                )
            ).all()
            return tuple(_to_domain(model) for model in models)
