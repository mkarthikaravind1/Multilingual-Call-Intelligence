from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider
from app.api.dependencies import ApiServices
from app.composition.services import (
    build_estimation_service,
    build_post_call_summary_service,
)
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.conversation_analysis_service import ConversationAnalysisService
from app.services.conversation_coverage_repository import ConversationCoverageRepository
from app.services.conversation_repository import ConversationRepository
from app.services.conversation_service import ConversationService
from app.services.in_memory_conversation_coverage_repository import (
    InMemoryConversationCoverageRepository,
)
from app.services.in_memory_conversation_repository import (
    InMemoryConversationRepository,
)
from app.services.next_question_service import NextQuestionService
from app.services.sentiment_analysis_service import SentimentAnalysisService
from app.composition.learning import build_learning_management_service
from app.services.learning_management_service import LearningManagementService
from app.composition.learning import build_learning_call_recorder
from app.domain.learning_evidence_repository import (
    InMemoryLearningEvidenceRepository,
    LearningEvidenceRepository,
)
from app.domain.learning_observation_repository import (
    InMemoryLearningObservationRepository,
    LearningObservationRepository,
)
from app.domain.improvement_candidate_repository import (
    ImprovementCandidateRepository,
    InMemoryImprovementCandidateRepository,
)
from app.composition.learning import (
    build_improvement_effectiveness_service,
    build_runtime_improvement_service,
)
from app.domain.active_improvement_repository import (
    ActiveImprovementRepository,
    InMemoryActiveImprovementRepository,
)
from app.domain.improvement_usage_repository import (
    ImprovementUsageRepository,
    InMemoryImprovementUsageRepository,
)
from app.domain.user_repository import InMemoryUserRepository, UserRepository
from app.services.auth_service import AuthService
from app.domain.user_repository import InMemoryUserRepository, UserRepository
from app.services.auth_service import AuthService

def build_api_services(
    complaint_provider: ComplaintDetectionProvider,
    sentiment_provider: SentimentAnalysisProvider,
    question_provider: QuestionSuggestionProvider,
    learning_service: LearningManagementService | None = None,
    conversation_repository: ConversationRepository | None = None,
    coverage_repository: ConversationCoverageRepository | None = None,
    evidence_repository: LearningEvidenceRepository | None = None,
    observation_repository: LearningObservationRepository | None = None,
    candidate_repository: ImprovementCandidateRepository | None = None,
    active_improvement_repository: ActiveImprovementRepository | None = None,
    usage_repository: ImprovementUsageRepository | None = None,
    user_repository: UserRepository | None = None,
    
) -> ApiServices:
    """Build the services the live application uses.

    Every repository is injectable so the composition root (main.py) can
    pass PostgreSQL-backed repositories in production while tests keep
    getting the in-memory defaults below.
    """
    conversation_repository = conversation_repository or InMemoryConversationRepository()
    coverage_repository = coverage_repository or InMemoryConversationCoverageRepository()
    evidence_repository = evidence_repository or InMemoryLearningEvidenceRepository()
    observation_repository = observation_repository or InMemoryLearningObservationRepository()
    candidate_repository = candidate_repository or InMemoryImprovementCandidateRepository()
    active_improvement_repository = (
        active_improvement_repository or InMemoryActiveImprovementRepository()
    )
    usage_repository = usage_repository or InMemoryImprovementUsageRepository()

    call_service = CallService(ConversationService(conversation_repository))

    runtime_improvement_service = build_runtime_improvement_service(
        active_improvement_repository
    )

    improvement_effectiveness_service = build_improvement_effectiveness_service(
        usage_repository=usage_repository,
        evidence_repository=evidence_repository,
    )

    workflow_service = CallWorkflowService(
        call_service,
        coverage_repository,
        ConversationAnalysisService(
            ComplaintAnalysisService(complaint_provider),
            SentimentAnalysisService(sentiment_provider),
        ),
        NextQuestionService(
            provider=question_provider,
            runtime_improvement_service=runtime_improvement_service,
            improvement_usage_recorder=improvement_effectiveness_service,
        ),
        build_estimation_service(),
        build_post_call_summary_service(),
        learning_recorder=build_learning_call_recorder(
            evidence_repository=evidence_repository,
            observation_repository=observation_repository,
        ),
    )

    user_repository = user_repository or InMemoryUserRepository()
    auth_service = AuthService(user_repository)

    return ApiServices(
        call_service=call_service,
        workflow_service=workflow_service,
        learning=learning_service
        or build_learning_management_service(
            evidence_repository=evidence_repository,
            candidate_repository=candidate_repository,
        ),
        auth=auth_service,
        user_repository=user_repository,
    )