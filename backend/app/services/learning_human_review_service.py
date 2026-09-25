from app.domain.improvement_candidate import ImprovementCandidate
from app.domain.improvement_candidate_repository import ImprovementCandidateRepository
from app.services.human_review_service import HumanReviewService


class LearningHumanReviewService:
    def __init__(
        self,
        review_service: HumanReviewService,
        repository: ImprovementCandidateRepository | None = None,
    ) -> None:
        self._review_service = review_service
        self._repository = repository

    def approve(
        self, candidate: ImprovementCandidate, reviewed_at: float | None = None
    ) -> ImprovementCandidate:
        self._require_candidate(candidate)
        return self._persist(self._review_service.approve(candidate, reviewed_at=reviewed_at))

    def reject(
        self, candidate: ImprovementCandidate, reviewed_at: float | None = None
    ) -> ImprovementCandidate:
        self._require_candidate(candidate)
        return self._persist(self._review_service.reject(candidate, reviewed_at=reviewed_at))

    def _persist(self, reviewed: ImprovementCandidate) -> ImprovementCandidate:
        if self._repository is not None:
            self._repository.save(reviewed)
        return reviewed

    @staticmethod
    def _require_candidate(candidate: ImprovementCandidate) -> None:
        if not isinstance(candidate, ImprovementCandidate):
            raise TypeError("candidate must be an ImprovementCandidate.")