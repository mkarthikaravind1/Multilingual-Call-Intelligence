from app.domain.improvement_candidate_repository import (
    ImprovementCandidateRepository,
    InMemoryImprovementCandidateRepository,
)
from app.domain.learning_evidence_repository import (
    InMemoryLearningEvidenceRepository,
    LearningEvidenceRepository,
)
from app.services.human_review_service import HumanReviewService
from app.services.learning_evidence_service import LearningEvidenceService
from app.services.learning_human_review_service import LearningHumanReviewService
from app.services.learning_management_service import LearningManagementService
from app.services.learning_pattern_discovery_service import (
    LearningPatternDiscoveryService,
)
from app.domain.learning_observation_repository import (
    InMemoryLearningObservationRepository,
    LearningObservationRepository,
)
from app.services.learning_call_integration_service import LearningCallIntegrationService
from app.services.learning_evidence_generation_service import (
    LearningEvidenceGenerationService,
)
from app.services.learning_observation_service import LearningObservationService


def build_learning_management_service(
    evidence_repository: LearningEvidenceRepository | None = None,
    candidate_repository: ImprovementCandidateRepository | None = None,
) -> LearningManagementService:
    evidence_repository = evidence_repository or InMemoryLearningEvidenceRepository()
    candidate_repository = candidate_repository or InMemoryImprovementCandidateRepository()
    evidence_service = LearningEvidenceService(evidence_repository)
    return LearningManagementService(
        evidence_service,
        LearningPatternDiscoveryService(evidence_service),
        candidate_repository,
        LearningHumanReviewService(HumanReviewService(), candidate_repository),
    )

def build_learning_call_recorder(
    evidence_repository: LearningEvidenceRepository | None = None,
    observation_repository: LearningObservationRepository | None = None,
) -> LearningCallIntegrationService:
    return LearningCallIntegrationService(
        LearningObservationService(
            observation_repository or InMemoryLearningObservationRepository()
        ),
        LearningEvidenceGenerationService(
            LearningEvidenceService(
                evidence_repository or InMemoryLearningEvidenceRepository()
            )
        ),
    )