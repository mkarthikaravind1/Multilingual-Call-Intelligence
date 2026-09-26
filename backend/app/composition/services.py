from collections.abc import Callable, Sequence
from uuid import uuid4

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
    create_summary_provider,
)
from app.core.config import Settings
from app.services.audio_processing_pipeline import (
    AudioProcessingPipeline,
    UtteranceProcessor,
)
from app.services.call_service import CallService
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.conversation_analysis_service import ConversationAnalysisService
from app.services.conversation_coverage_repository import (
    ConversationCoverageRepository,
)
from app.services.conversation_repository import ConversationRepository
from app.services.conversation_service import ConversationService
from app.composition.providers import create_coverage_repository
from app.services.in_memory_conversation_repository import (
    InMemoryConversationRepository,
)
from app.services.next_question_service import NextQuestionService
from app.services.sentiment_analysis_service import SentimentAnalysisService
from app.estimation.default_pricing import DEFAULT_PRICING_CONFIG
from app.estimation.provider import ServiceEstimationProvider
from app.estimation.rule_based_provider import RuleBasedEstimationProvider
from app.services.estimation_service import EstimationService
from app.ai.summary.rule_based_provider import RuleBasedSummaryProvider
from app.domain.customer_contact import CustomerContact, MessagingChannel
from app.services.post_call_summary_service import PostCallSummaryService
from app.services.customer_summary_delivery_service import (
    CustomerSummaryDeliveryProvider,
    CustomerSummaryDeliveryService,
)
from app.services.customer_summary_message_service import CustomerSummaryMessageService
from app.services.call_workflow_service import (
    AnalysisLearningRecorder,
    CallWorkflowService,
)
from app.domain.active_improvement_repository import (
    ActiveImprovementRepository,
)
from app.domain.improvement_usage_repository import (
    ImprovementUsageRepository,
)
from app.domain.learning_evidence_repository import (
    LearningEvidenceRepository,
)
from app.services.improvement_effectiveness_service import (
    ImprovementEffectivenessService,
)
from app.services.runtime_improvement_service import (
    RuntimeImprovementService,
)

def build_post_call_summary_service(
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
) -> PostCallSummaryService:
    return PostCallSummaryService(
        create_summary_provider(llm_client=llm_client, settings=settings)
    )


class NullCustomerSummaryDeliveryProvider(CustomerSummaryDeliveryProvider):
    def send_summary(
        self,
        contact: CustomerContact,
        message: str,
        channel: MessagingChannel,
    ) -> str:
        return f"noop-{uuid4()}"


def create_customer_summary_delivery_provider(
    settings: Settings | None = None,
) -> CustomerSummaryDeliveryProvider:
    settings = settings or Settings()
    provider_name = settings.customer_summary_delivery_provider.strip().lower()
    if provider_name in {"disabled", "none", "null", "noop"}:
        return NullCustomerSummaryDeliveryProvider()
    raise ValueError(
        f"Unsupported customer summary delivery provider: {provider_name!r}. "
        "Configure customer_summary_delivery_provider to one of: disabled, noop."
    )


def build_customer_summary_delivery_service(
    settings: Settings | None = None,
    provider: CustomerSummaryDeliveryProvider | None = None,
) -> CustomerSummaryDeliveryService:
    settings = settings or Settings()
    provider = provider or create_customer_summary_delivery_provider(settings)
    return CustomerSummaryDeliveryService(
        provider=provider,
        message_service=CustomerSummaryMessageService(
            default_channel=MessagingChannel(settings.customer_summary_default_channel)
        ),
        require_consent=settings.customer_summary_consent_required,
    )


def build_conversation_repository() -> ConversationRepository:
    return InMemoryConversationRepository()


def build_coverage_repository(
    settings: Settings | None = None,
) -> ConversationCoverageRepository:
    return create_coverage_repository(settings)

def build_estimation_service(
    provider: ServiceEstimationProvider | None = None,
) -> EstimationService:
    provider = provider or RuleBasedEstimationProvider(
        DEFAULT_PRICING_CONFIG
    )

    return EstimationService(provider)

def build_call_service(repository: ConversationRepository | None = None) -> CallService:
    return CallService(ConversationService(repository or build_conversation_repository()))


def build_next_question_service(
    provider: QuestionSuggestionProvider,
    runtime_improvement_service: RuntimeImprovementService | None = None,
    improvement_usage_recorder: ImprovementEffectivenessService | None = None,
) -> NextQuestionService:
    return NextQuestionService(
        provider=provider,
        runtime_improvement_service=runtime_improvement_service,
        improvement_usage_recorder=improvement_usage_recorder,
    )

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
    estimation_service: EstimationService | None = None,
    post_call_summary_service: PostCallSummaryService | None = None,
    customer_summary_delivery_service: CustomerSummaryDeliveryService | None = None,
    customer_contact_resolver: Callable[[str], CustomerContact | None] | None = None,
    learning_recorder: AnalysisLearningRecorder | None = None,
    runtime_improvement_service: RuntimeImprovementService | None = None,
    improvement_usage_recorder: ImprovementEffectivenessService | None = None,
) -> CallWorkflowService:
    if llm_client is None:
        llm_client = create_llm_client(settings)

    return CallWorkflowService(
        call_service=call_service or build_call_service(),
        coverage_repository=coverage_repository or build_coverage_repository(settings),
        analysis_service=build_conversation_analysis_service(
            complaint_provider=create_complaint_provider(llm_client),
            sentiment_provider=create_sentiment_provider(llm_client),
        ),
        next_question_service=build_next_question_service(
            provider=create_question_provider(llm_client),
            runtime_improvement_service=runtime_improvement_service,
            improvement_usage_recorder=improvement_usage_recorder,
        ),
        estimation_service=estimation_service or build_estimation_service(),
        post_call_summary_service=post_call_summary_service
        or build_post_call_summary_service(settings=settings, llm_client=llm_client),
        customer_summary_delivery_service=customer_summary_delivery_service,
        customer_contact_resolver=customer_contact_resolver,
        learning_recorder=learning_recorder,
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
        diarization_provider=create_diarization_provider(
            diarization_segments, settings
        ),
        role_provider=role_provider or create_role_provider(settings),
        workflow_service=workflow_service,
    )