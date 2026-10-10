from collections.abc import Callable, Sequence

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
from app.domain.active_improvement_repository import (
    ActiveImprovementRepository,
    InMemoryActiveImprovementRepository,
)
from app.domain.improvement_usage_repository import (
    ImprovementUsageRepository,
    InMemoryImprovementUsageRepository,
)
from app.services.improvement_effectiveness_service import (
    ImprovementEffectivenessService,
)
from app.services.runtime_improvement_service import (
    RuntimeImprovementService,
)
from app.domain.learning_feedback_repository import (
    InMemoryLearningFeedbackRepository,
    LearningFeedbackRepository,
)
from app.services.improvement_application_service import ImprovementApplicationService
from app.services.improvement_candidate_service import ImprovementCandidateService
from app.services.learning_candidate_generation_service import (
    LearningCandidateGenerationService,
)
from app.services.learning_feedback_service import LearningFeedbackService
from app.services.pattern_discovery_service import PatternRules

def build_learning_management_service(
    evidence_repository: LearningEvidenceRepository | None = None,
    candidate_repository: ImprovementCandidateRepository | None = None,
    observation_repository: LearningObservationRepository | None = None,
    feedback_repository: LearningFeedbackRepository | None = None,
    active_improvement_repository: ActiveImprovementRepository | None = None,
    usage_repository: ImprovementUsageRepository | None = None,
    complaint_categories: Callable[[], Sequence[str]] | None = None,
    pattern_rules: PatternRules | None = None,
) -> LearningManagementService:
    """The whole learning loop. Pass the same repositories the runtime uses
    (notably active_improvement_repository) so approvals reach live calls."""
    evidence_repository = evidence_repository or InMemoryLearningEvidenceRepository()
    candidate_repository = candidate_repository or InMemoryImprovementCandidateRepository()
    observation_repository = (
        observation_repository or InMemoryLearningObservationRepository()
    )
    feedback_repository = feedback_repository or InMemoryLearningFeedbackRepository()
    active_improvement_repository = (
        active_improvement_repository or InMemoryActiveImprovementRepository()
    )
    evidence_service = LearningEvidenceService(evidence_repository)
    observation_service = LearningObservationService(observation_repository)
    return LearningManagementService(
        evidence_service,
        LearningPatternDiscoveryService(evidence_service, rules=pattern_rules),
        candidate_repository,
        LearningHumanReviewService(HumanReviewService(), candidate_repository),
        observation_service=observation_service,
        feedback_service=LearningFeedbackService(feedback_repository, observation_service),
        evidence_generation=LearningEvidenceGenerationService(evidence_service),
        candidate_generation=LearningCandidateGenerationService(
            ImprovementCandidateService(), repository=candidate_repository, rules=pattern_rules
        ),
        application_service=ImprovementApplicationService(active_improvement_repository),
        effectiveness_service=build_improvement_effectiveness_service(
            usage_repository=usage_repository,
            evidence_repository=evidence_repository,
        ),
        complaint_categories=complaint_categories,
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

def build_runtime_improvement_service(
    repository: ActiveImprovementRepository | None = None,
) -> RuntimeImprovementService:
    return RuntimeImprovementService(
        repository
        or InMemoryActiveImprovementRepository()
    )


def build_improvement_effectiveness_service(
    usage_repository: ImprovementUsageRepository | None = None,
    evidence_repository: LearningEvidenceRepository | None = None,
) -> ImprovementEffectivenessService:
    return ImprovementEffectivenessService(
        usage_repository
        or InMemoryImprovementUsageRepository(),
        evidence_repository
        or InMemoryLearningEvidenceRepository(),
    )