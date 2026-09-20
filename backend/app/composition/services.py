from collections.abc import Sequence

from app.ai.asr.provider import ASRProvider
from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.language.provider import LanguageIdentificationProvider
from app.ai.llm.client import LLMClient
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider
from app.ai.speaker.provider import DiarizedSegment, RoleIdentificationProvider
from app.composition.providers import (
    create_asr_provider,
    create_complaint_provider,
    create_diarization_provider,
    create_language_provider,
    create_llm_client,
    create_question_provider,
    create_role_provider,
    create_sentiment_provider,
)
from app.core.config import Settings
from app.services.audio_processing_pipeline import (
    AudioProcessingPipeline,
    UtteranceProcessor,
)
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.conversation_analysis_service import ConversationAnalysisService
from app.services.conversation_coverage_repository import (
    ConversationCoverageRepository,
)
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
from app.services import *


def build_conversation_repository() -> ConversationRepository:
    return InMemoryConversationRepository()


def build_coverage_repository() -> ConversationCoverageRepository:
    return InMemoryConversationCoverageRepository()


def build_call_service(repository: ConversationRepository | None = None) -> CallService:
    return CallService(ConversationService(repository or build_conversation_repository()))


def build_next_question_service(
    provider: QuestionSuggestionProvider,
) -> NextQuestionService:
    return NextQuestionService(provider)


def build_conversation_analysis_service(
    complaint_provider: ComplaintDetectionProvider,
    sentiment_provider: SentimentAnalysisProvider,
) -> ConversationAnalysisService:
    return ConversationAnalysisService(
        complaint_service=ComplaintAnalysisService(complaint_provider),
        sentiment_service=SentimentAnalysisService(sentiment_provider),
    )


def build_call_workflow_service(
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
    call_service: CallService | None = None,
    coverage_repository: ConversationCoverageRepository | None = None,
) -> CallWorkflowService:
        if llm_client is None:
            llm_client = create_llm_client(settings)

        return CallWorkflowService(
            call_service=call_service or build_call_service(),
            coverage_repository=coverage_repository or build_coverage_repository(),
            analysis_service=build_conversation_analysis_service(
                complaint_provider=create_complaint_provider(llm_client),
                sentiment_provider=create_sentiment_provider(llm_client),
            ),
            next_question_service=build_next_question_service(
                create_question_provider(llm_client)
            ),
    )


def build_audio_processing_pipeline(
    workflow_service: UtteranceProcessor,
    diarization_segments: Sequence[DiarizedSegment],
    settings: Settings | None = None,
    asr_provider: ASRProvider | None = None,
    language_provider: LanguageIdentificationProvider | None = None,
    role_provider: RoleIdentificationProvider | None = None,
) -> AudioProcessingPipeline:
        return AudioProcessingPipeline(
        asr_provider=asr_provider or create_asr_provider(settings),
        language_provider=language_provider or create_language_provider(settings),
        diarization_provider=create_diarization_provider(diarization_segments),
        role_provider=role_provider or create_role_provider(),
        workflow_service=workflow_service,
    )