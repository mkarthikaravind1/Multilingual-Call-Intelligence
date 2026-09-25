"""Applies an APPROVED ImprovementCandidate as an ActiveImprovement.

This is the boundary the prompt calls out explicitly: it registers data,
it never touches an AI provider, a prompt, or CallWorkflowService. SL-12
is responsible for anything that reads this registry at runtime."""

import time
from uuid import uuid4

from app.domain.active_improvement import ActiveImprovement, ActiveImprovementStatus
from app.domain.active_improvement_repository import ActiveImprovementRepository
from app.domain.improvement_candidate import ImprovementCandidate, ImprovementReviewStatus


class ImprovementNotApprovedError(Exception):
    def __init__(self, candidate_id: str, status: ImprovementReviewStatus) -> None:
        super().__init__(
            f"Candidate {candidate_id!r} is {status.value}; only APPROVED "
            "candidates can be activated."
        )
        self.candidate_id = candidate_id
        self.status = status


class MissingImprovementSpecificationError(Exception):
    def __init__(self, candidate_id: str) -> None:
        super().__init__(
            f"Candidate {candidate_id!r} has no specification; cannot activate."
        )
        self.candidate_id = candidate_id


class ActiveImprovementNotFoundError(Exception):
    def __init__(self, improvement_id: str) -> None:
        super().__init__(f"No active improvement found for improvement_id={improvement_id!r}.")
        self.improvement_id = improvement_id


class ImprovementApplicationService:
    def __init__(self, repository: ActiveImprovementRepository) -> None:
        self._repository = repository

    def activate(
        self,
        candidate: ImprovementCandidate,
        activated_at: float | None = None,
    ) -> ActiveImprovement:
        if candidate.status is not ImprovementReviewStatus.APPROVED:
            raise ImprovementNotApprovedError(candidate.candidate_id, candidate.status)
        if candidate.specification is None:
            raise MissingImprovementSpecificationError(candidate.candidate_id)

        existing = self._repository.get_by_candidate_id(candidate.candidate_id)
        if existing is not None and existing.status is ActiveImprovementStatus.ACTIVE:
            return existing

        timestamp = time.time() if activated_at is None else activated_at
        improvement = ActiveImprovement(
            improvement_id=f"improvement-{uuid4()}",
            candidate_id=candidate.candidate_id,
            component=candidate.specification.component,
            specification=candidate.specification,
            status=ActiveImprovementStatus.ACTIVE,
            activated_at=timestamp,
        )
        self._repository.save(improvement)
        return improvement

    def get(self, improvement_id: str) -> ActiveImprovement:
        improvement = self._repository.get(improvement_id)
        if improvement is None:
            raise ActiveImprovementNotFoundError(improvement_id)
        return improvement

    def list_active(self) -> tuple[ActiveImprovement, ...]:
        return self._repository.list_active()

    def list_all(self) -> tuple[ActiveImprovement, ...]:
        return self._repository.list_all()

    def deactivate(self, improvement_id: str, at: float | None = None) -> ActiveImprovement:
        improvement = self.get(improvement_id)
        timestamp = time.time() if at is None else at
        deactivated = improvement.deactivate(timestamp)
        self._repository.save(deactivated)
        return deactivated