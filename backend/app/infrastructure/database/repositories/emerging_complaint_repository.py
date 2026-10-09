from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.emerging_complaint_candidate import (
    EmergingComplaintCandidate,
    EmergingComplaintReviewError,
    EmergingComplaintReviewStatus,
)
from app.infrastructure.database.models import EmergingComplaintCandidateModel
from app.services.emerging_complaint_repository import EmergingComplaintRepository

_COLUMNS = (
    "proposed_name",
    "description",
    "occurrence_count",
    "confidence",
    "related_category",
    "first_seen_at",
    "last_seen_at",
    "reviewed_by",
    "reviewed_at",
    "review_note",
    "category_name",
    "category_description",
)


def _apply(model: EmergingComplaintCandidateModel, candidate: EmergingComplaintCandidate) -> None:
    for column in _COLUMNS:
        setattr(model, column, getattr(candidate, column))
    model.evidence = list(candidate.evidence)
    model.call_ids = list(candidate.call_ids)
    model.status = candidate.status.value


def _to_domain(model: EmergingComplaintCandidateModel) -> EmergingComplaintCandidate:
    return EmergingComplaintCandidate(
        candidate_id=model.candidate_id,
        evidence=tuple(model.evidence),
        call_ids=tuple(model.call_ids),
        status=EmergingComplaintReviewStatus(model.status),
        **{column: getattr(model, column) for column in _COLUMNS},
    )


class PostgresEmergingComplaintRepository(EmergingComplaintRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, candidate_id: str) -> EmergingComplaintCandidate | None:
        with self._session_factory() as session:
            model = session.get(EmergingComplaintCandidateModel, candidate_id)
            return None if model is None else _to_domain(model)

    def save(self, candidate: EmergingComplaintCandidate) -> None:
        try:
            with self._session_factory() as session, session.begin():
                model = session.get(EmergingComplaintCandidateModel, candidate.candidate_id)
                if model is None:
                    model = EmergingComplaintCandidateModel(candidate_id=candidate.candidate_id)
                    session.add(model)
                _apply(model, candidate)
        except IntegrityError as exc:
            # Only the accepted-category-name index can refuse an update:
            # another instance accepted a theme with this name meanwhile.
            if candidate.status is not EmergingComplaintReviewStatus.ACCEPTED:
                raise
            raise EmergingComplaintReviewError(
                f"There is already a category called {candidate.category_name!r}; "
                "choose another name."
            ) from exc

    def list_by_status(
        self, statuses: Iterable[EmergingComplaintReviewStatus]
    ) -> tuple[EmergingComplaintCandidate, ...]:
        values = [status.value for status in statuses]
        with self._session_factory() as session:
            stmt = select(EmergingComplaintCandidateModel).where(
                EmergingComplaintCandidateModel.status.in_(values)
            )
            return tuple(_to_domain(model) for model in session.scalars(stmt))
