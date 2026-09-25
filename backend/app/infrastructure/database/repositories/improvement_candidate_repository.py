from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.improvement_candidate import (
    ImprovementCandidate,
    ImprovementReviewStatus,
    ImprovementSpecification,
    ImprovementType,
)
from app.domain.improvement_candidate_repository import ImprovementCandidateRepository
from app.domain.learning_evidence import LearningComponent
from app.infrastructure.database.models import ImprovementCandidateModel


def _spec_to_domain(
    model: ImprovementCandidateModel,
) -> ImprovementSpecification | None:
    spec_component = model.spec_component
    current_behavior = model.spec_current_behavior
    proposed_behavior = model.spec_proposed_behavior
    reason = model.spec_reason

    # No specification was persisted.
    if spec_component is None:
        # A partial specification is invalid database state.
        if any(
            value is not None
            for value in (current_behavior, proposed_behavior, reason)
        ):
            raise ValueError(
                "Improvement candidate contains a partial specification."
            )
        return None

    # If a specification exists, all of its fields must exist.
    if current_behavior is None:
        raise ValueError(
            "Improvement candidate specification is missing current_behavior."
        )

    if proposed_behavior is None:
        raise ValueError(
            "Improvement candidate specification is missing proposed_behavior."
        )

    if reason is None:
        raise ValueError(
            "Improvement candidate specification is missing reason."
        )

    return ImprovementSpecification(
        component=LearningComponent(spec_component),
        current_behavior=current_behavior,
        proposed_behavior=proposed_behavior,
        reason=reason,
    )



def _to_domain(model: ImprovementCandidateModel) -> ImprovementCandidate:
    return ImprovementCandidate(
        candidate_id=model.candidate_id,
        improvement_type=ImprovementType(model.improvement_type),
        title=model.title,
        description=model.description,
        evidence=tuple(model.evidence),
        occurrence_count=model.occurrence_count,
        confidence=model.confidence,
        status=ImprovementReviewStatus(model.status),
        created_at=model.created_at,
        reviewed_at=model.reviewed_at,
        specification=_spec_to_domain(model),
    )


def _to_model(candidate: ImprovementCandidate) -> ImprovementCandidateModel:
    spec = candidate.specification
    return ImprovementCandidateModel(
        candidate_id=candidate.candidate_id,
        improvement_type=candidate.improvement_type.value,
        title=candidate.title,
        description=candidate.description,
        evidence=list(candidate.evidence),
        occurrence_count=candidate.occurrence_count,
        confidence=candidate.confidence,
        status=candidate.status.value,
        created_at=candidate.created_at,
        reviewed_at=candidate.reviewed_at,
        spec_component=None if spec is None else spec.component.value,
        spec_current_behavior=None if spec is None else spec.current_behavior,
        spec_proposed_behavior=None if spec is None else spec.proposed_behavior,
        spec_reason=None if spec is None else spec.reason,
    )


class PostgresImprovementCandidateRepository(ImprovementCandidateRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, candidate: ImprovementCandidate) -> None:
        with self._session_factory() as session, session.begin():
            existing = session.get(ImprovementCandidateModel, candidate.candidate_id)
            if existing is not None:
                session.delete(existing)
                session.flush()
            session.add(_to_model(candidate))

    def get(self, candidate_id: str) -> ImprovementCandidate | None:
        with self._session_factory() as session:
            model = session.get(ImprovementCandidateModel, candidate_id)
            return None if model is None else _to_domain(model)

    def list_all(self) -> tuple[ImprovementCandidate, ...]:
        with self._session_factory() as session:
            models = session.scalars(select(ImprovementCandidateModel)).all()
            return tuple(_to_domain(model) for model in models)