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
from app.domain.learning_evidence_repository import InMemoryLearningEvidenceRepository

def build_api_services(
    complaint_provider: ComplaintDetectionProvider,
    sentiment_provider: SentimentAnalysisProvider,
    question_provider: QuestionSuggestionProvider,
    learning_service: LearningManagementService | None = None,
) -> ApiServices:
    call_service = CallService(
        ConversationService(
            InMemoryConversationRepository()
        )
    )

    evidence_repository = InMemoryLearningEvidenceRepository()

    workflow_service = CallWorkflowService(
        call_service,
        InMemoryConversationCoverageRepository(),
        ConversationAnalysisService(
            ComplaintAnalysisService(complaint_provider),
            SentimentAnalysisService(sentiment_provider),
        ),
        NextQuestionService(question_provider),
        build_estimation_service(),
        build_post_call_summary_service(),
        learning_recorder=build_learning_call_recorder(evidence_repository),
    )

    return ApiServices(
        call_service=call_service,
        workflow_service=workflow_service,
        learning=learning_service
        or build_learning_management_service(evidence_repository),
    )