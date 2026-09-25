from app.domain.improvement_candidate import ImprovementCandidate
from app.domain.improvement_candidate_repository import ImprovementCandidateRepository
from app.domain.learning_evidence import LearningEvidence
from app.domain.learning_pattern import LearningPattern
from app.services.learning_evidence_service import LearningEvidenceService
from app.services.learning_human_review_service import LearningHumanReviewService
from app.services.learning_pattern_discovery_service import (
    LearningPatternDiscoveryService,
)


class CandidateNotFoundError(Exception):
    def __init__(self, candidate_id: str) -> None:
        super().__init__(f"No improvement candidate found with id: {candidate_id!r}")
        self.candidate_id = candidate_id


class CandidateReviewConflictError(Exception):
    pass


class LearningManagementService:
    def __init__(
        self,
        evidence_service: LearningEvidenceService,
        pattern_discovery: LearningPatternDiscoveryService,
        candidate_repository: ImprovementCandidateRepository,
        review_service: LearningHumanReviewService,
    ) -> None:
        self._evidence_service = evidence_service
        self._pattern_discovery = pattern_discovery
        self._candidate_repository = candidate_repository
        self._review_service = review_service

    def list_candidates(self) -> tuple[ImprovementCandidate, ...]:
        return self._candidate_repository.list_all()

    def get_candidate(self, candidate_id: str) -> ImprovementCandidate:
        candidate = self._candidate_repository.get(candidate_id)
        if candidate is None:
            raise CandidateNotFoundError(candidate_id)
        return candidate

    def approve(self, candidate_id: str) -> ImprovementCandidate:
        candidate = self.get_candidate(candidate_id)
        try:
            return self._review_service.approve(candidate)
        except ValueError as exc:
            raise CandidateReviewConflictError(str(exc)) from exc

    def reject(self, candidate_id: str) -> ImprovementCandidate:
        candidate = self.get_candidate(candidate_id)
        try:
            return self._review_service.reject(candidate)
        except ValueError as exc:
            raise CandidateReviewConflictError(str(exc)) from exc

    def list_patterns(self) -> list[LearningPattern]:
        return self._pattern_discovery.discover()

    def list_evidence(self) -> tuple[LearningEvidence, ...]:
        return self._evidence_service.list_all()