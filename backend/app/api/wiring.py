from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider
from app.api.dependencies import ApiServices
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


def build_api_services(
    complaint_provider: ComplaintDetectionProvider,
    sentiment_provider: SentimentAnalysisProvider,
    question_provider: QuestionSuggestionProvider,
) -> ApiServices:
    call_service = CallService(ConversationService(InMemoryConversationRepository()))
    workflow_service = CallWorkflowService(
        call_service,
        InMemoryConversationCoverageRepository(),
        ConversationAnalysisService(
            ComplaintAnalysisService(complaint_provider),
            SentimentAnalysisService(sentiment_provider),
        ),
        NextQuestionService(question_provider),
    )
    return ApiServices(call_service=call_service, workflow_service=workflow_service)