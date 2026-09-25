from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.learning_evidence import LearningComponent
from app.domain.learning_observation import LearningObservation
from app.domain.learning_observation_repository import LearningObservationRepository
from app.infrastructure.database.models import LearningObservationModel


def _to_domain(model: LearningObservationModel) -> LearningObservation:
    return LearningObservation(
        observation_id=model.observation_id,
        call_id=model.call_id,
        component=LearningComponent(model.component),
        description=model.description,
        predicted_value=model.predicted_value,
        confidence=model.confidence,
        created_at=model.created_at,
        entity_id=model.entity_id,
    )


def _to_model(observation: LearningObservation) -> LearningObservationModel:
    return LearningObservationModel(
        observation_id=observation.observation_id,
        call_id=observation.call_id,
        component=observation.component.value,
        description=observation.description,
        predicted_value=observation.predicted_value,
        confidence=observation.confidence,
        created_at=observation.created_at,
        entity_id=observation.entity_id,
    )


class PostgresLearningObservationRepository(LearningObservationRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, observation: LearningObservation) -> None:
        with self._session_factory() as session, session.begin():
            existing = session.get(LearningObservationModel, observation.observation_id)
            if existing is not None:
                session.delete(existing)
                session.flush()
            session.add(_to_model(observation))

    def get(self, observation_id: str) -> LearningObservation | None:
        with self._session_factory() as session:
            model = session.get(LearningObservationModel, observation_id)
            return None if model is None else _to_domain(model)

    def get_by_call_id(self, call_id: str) -> tuple[LearningObservation, ...]:
        with self._session_factory() as session:
            stmt = select(LearningObservationModel).where(
                LearningObservationModel.call_id == call_id
            )
            models = session.scalars(stmt).all()
            return tuple(_to_domain(model) for model in models)

    def list_all(self) -> tuple[LearningObservation, ...]:
        with self._session_factory() as session:
            models = session.scalars(select(LearningObservationModel)).all()
            return tuple(_to_domain(model) for model in models)