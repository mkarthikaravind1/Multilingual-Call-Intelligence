from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.improvement_usage import ImprovementUsage
from app.domain.improvement_usage_repository import ImprovementUsageRepository
from app.domain.learning_evidence import LearningComponent
from app.infrastructure.database.models import ImprovementUsageModel


def _to_domain(model: ImprovementUsageModel) -> ImprovementUsage:
    return ImprovementUsage(
        usage_id=model.usage_id,
        improvement_id=model.improvement_id,
        candidate_id=model.candidate_id,
        call_id=model.call_id,
        component=LearningComponent(model.component),
        output_value=model.output_value,
        used_at=model.used_at,
    )


def _to_model(usage: ImprovementUsage) -> ImprovementUsageModel:
    return ImprovementUsageModel(
        usage_id=usage.usage_id,
        improvement_id=usage.improvement_id,
        candidate_id=usage.candidate_id,
        call_id=usage.call_id,
        component=usage.component.value,
        output_value=usage.output_value,
        used_at=usage.used_at,
    )


class PostgresImprovementUsageRepository(ImprovementUsageRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, usage: ImprovementUsage) -> None:
        with self._session_factory() as session, session.begin():
            existing = session.get(ImprovementUsageModel, usage.usage_id)
            if existing is not None:
                session.delete(existing)
                session.flush()
            session.add(_to_model(usage))

    def get(self, usage_id: str) -> ImprovementUsage | None:
        with self._session_factory() as session:
            model = session.get(ImprovementUsageModel, usage_id)
            return None if model is None else _to_domain(model)

    def list_all(self) -> tuple[ImprovementUsage, ...]:
        with self._session_factory() as session:
            models = session.scalars(select(ImprovementUsageModel)).all()
            return tuple(_to_domain(model) for model in models)

    def list_for_improvement(self, improvement_id: str) -> tuple[ImprovementUsage, ...]:
        with self._session_factory() as session:
            stmt = select(ImprovementUsageModel).where(
                ImprovementUsageModel.improvement_id == improvement_id
            )
            models = session.scalars(stmt).all()
            return tuple(_to_domain(model) for model in models)

    def list_for_call(self, call_id: str) -> tuple[ImprovementUsage, ...]:
        with self._session_factory() as session:
            stmt = select(ImprovementUsageModel).where(
                ImprovementUsageModel.call_id == call_id
            )
            models = session.scalars(stmt).all()
            return tuple(_to_domain(model) for model in models)