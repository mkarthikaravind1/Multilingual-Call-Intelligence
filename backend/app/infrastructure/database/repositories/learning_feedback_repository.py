from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.learning_feedback import FeedbackSource, FeedbackType, LearningFeedback
from app.domain.learning_feedback_repository import LearningFeedbackRepository
from app.infrastructure.database.models import LearningFeedbackModel


def _to_domain(model: LearningFeedbackModel) -> LearningFeedback:
    return LearningFeedback(
        feedback_id=model.feedback_id,
        observation_id=model.observation_id,
        feedback_type=FeedbackType(model.feedback_type),
        corrected_value=model.corrected_value,
        outcome=model.outcome,
        created_at=model.created_at,
        call_id=model.call_id,
        original_value=model.original_value,
        source=FeedbackSource(model.source),
        notes=model.notes,
    )


def _to_model(feedback: LearningFeedback) -> LearningFeedbackModel:
    return LearningFeedbackModel(
        feedback_id=feedback.feedback_id,
        observation_id=feedback.observation_id,
        feedback_type=feedback.feedback_type.value,
        corrected_value=feedback.corrected_value,
        outcome=feedback.outcome,
        created_at=feedback.created_at,
        call_id=feedback.call_id,
        original_value=feedback.original_value,
        source=feedback.source.value,
        notes=feedback.notes,
    )


class PostgresLearningFeedbackRepository(LearningFeedbackRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, feedback: LearningFeedback) -> None:
        with self._session_factory() as session, session.begin():
            existing = session.get(LearningFeedbackModel, feedback.feedback_id)
            if existing is not None:
                session.delete(existing)
                session.flush()
            session.add(_to_model(feedback))

    def get(self, feedback_id: str) -> LearningFeedback | None:
        with self._session_factory() as session:
            model = session.get(LearningFeedbackModel, feedback_id)
            return None if model is None else _to_domain(model)

    def get_by_observation_id(self, observation_id: str) -> tuple[LearningFeedback, ...]:
        with self._session_factory() as session:
            stmt = select(LearningFeedbackModel).where(
                LearningFeedbackModel.observation_id == observation_id
            )
            models = session.scalars(stmt).all()
            return tuple(_to_domain(model) for model in models)

    def get_by_call_id(self, call_id: str) -> tuple[LearningFeedback, ...]:
        with self._session_factory() as session:
            stmt = select(LearningFeedbackModel).where(
                LearningFeedbackModel.call_id == call_id
            )
            models = session.scalars(stmt).all()
            return tuple(_to_domain(model) for model in models)

    def list_all(self) -> tuple[LearningFeedback, ...]:
        with self._session_factory() as session:
            models = session.scalars(select(LearningFeedbackModel)).all()
            return tuple(_to_domain(model) for model in models)