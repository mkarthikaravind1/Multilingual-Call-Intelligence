from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.active_improvement import ActiveImprovement, ActiveImprovementStatus
from app.domain.active_improvement_repository import ActiveImprovementRepository
from app.domain.improvement_candidate import ImprovementSpecification
from app.domain.learning_evidence import LearningComponent
from app.infrastructure.database.models import ActiveImprovementModel


def _to_domain(model: ActiveImprovementModel) -> ActiveImprovement:
    return ActiveImprovement(
        improvement_id=model.improvement_id,
        candidate_id=model.candidate_id,
        component=LearningComponent(model.component),
        specification=ImprovementSpecification(
            component=LearningComponent(model.spec_component),
            current_behavior=model.spec_current_behavior,
            proposed_behavior=model.spec_proposed_behavior,
            reason=model.spec_reason,
        ),
        status=ActiveImprovementStatus(model.status),
        activated_at=model.activated_at,
        deactivated_at=model.deactivated_at,
    )


def _to_model(improvement: ActiveImprovement) -> ActiveImprovementModel:
    spec = improvement.specification
    return ActiveImprovementModel(
        improvement_id=improvement.improvement_id,
        candidate_id=improvement.candidate_id,
        component=improvement.component.value,
        spec_component=spec.component.value,
        spec_current_behavior=spec.current_behavior,
        spec_proposed_behavior=spec.proposed_behavior,
        spec_reason=spec.reason,
        status=improvement.status.value,
        activated_at=improvement.activated_at,
        deactivated_at=improvement.deactivated_at,
    )


class PostgresActiveImprovementRepository(ActiveImprovementRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, improvement: ActiveImprovement) -> None:
        with self._session_factory() as session, session.begin():
            existing = session.get(ActiveImprovementModel, improvement.improvement_id)
            if existing is not None:
                session.delete(existing)
                session.flush()
            session.add(_to_model(improvement))

    def get(self, improvement_id: str) -> ActiveImprovement | None:
        with self._session_factory() as session:
            model = session.get(ActiveImprovementModel, improvement_id)
            return None if model is None else _to_domain(model)

    def get_by_candidate_id(self, candidate_id: str) -> ActiveImprovement | None:
        with self._session_factory() as session:
            stmt = select(ActiveImprovementModel).where(
                ActiveImprovementModel.candidate_id == candidate_id
            )
            model = session.scalars(stmt).first()
            return None if model is None else _to_domain(model)

    def list_all(self) -> tuple[ActiveImprovement, ...]:
        with self._session_factory() as session:
            models = session.scalars(select(ActiveImprovementModel)).all()
            return tuple(_to_domain(model) for model in models)

    def list_active(self) -> tuple[ActiveImprovement, ...]:
        with self._session_factory() as session:
            stmt = select(ActiveImprovementModel).where(
                ActiveImprovementModel.status == ActiveImprovementStatus.ACTIVE.value
            )
            models = session.scalars(stmt).all()
            return tuple(_to_domain(model) for model in models)

    def list_active_for_component(
        self, component: LearningComponent
    ) -> tuple[ActiveImprovement, ...]:
        with self._session_factory() as session:
            stmt = select(ActiveImprovementModel).where(
                ActiveImprovementModel.status == ActiveImprovementStatus.ACTIVE.value,
                ActiveImprovementModel.component == component.value,
            )
            models = session.scalars(stmt).all()
            return tuple(_to_domain(model) for model in models)