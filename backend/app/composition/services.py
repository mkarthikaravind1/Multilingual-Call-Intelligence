from collections.abc import Callable, Mapping, Sequence
from uuid import uuid4

from app.ai.asr.provider import ASRProvider
from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.language.provider import LanguageIdentificationProvider
from app.ai.live_analysis.llm_provider import LLMLiveAnalysisProvider
from app.ai.llm.client import LLMClient
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider
from app.ai.speaker.provider import DiarizedSegment, RoleIdentificationProvider
from app.composition.providers import (
    create_asr_provider,
    create_complaint_provider,
    create_diarization_provider,
    create_language_provider,
    UnsupportedProviderError,
    create_llm_client,
    create_question_provider,
    create_role_provider,
    create_sentiment_provider,
    create_summary_provider,
)
from app.core.config import Settings
from app.services.call_indicators import CallIndicators
from app.services.audio_processing_pipeline import (
    AudioProcessingPipeline,
    UtteranceProcessor,
)
from app.domain.conversation import Conversation
from app.domain.utterance import Utterance
from app.services.call_alerts import CallAlertService
from app.services.call_service import CallService
from app.services.complaint_lifecycle_service import ComplaintLifecycleService
from app.services.emerging_complaint_service import EmergingComplaintService
from app.services.escalation_service import EscalationService
from app.services.live_analysis_store import DEFAULT_LIVE_ANALYSIS_TTL_SECONDS
from app.services.live_state_store import LiveStateStore
from app.services.language_lock import LanguageLock
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
from app.estimation.pricing_config import PricingSource
from app.estimation.provider import ServiceEstimationProvider
from app.estimation.rule_based_provider import RuleBasedEstimationProvider
from app.estimation.detection import (
    KeywordServiceDetector,
    LLMServiceDetector,
    ServiceDetectionProvider,
)
from app.services.estimation_service import EstimationService
from app.ai.summary.rule_based_provider import RuleBasedSummaryProvider
from app.domain.customer_contact import CustomerContact, MessagingChannel
from app.services.post_call_summary_service import PostCallSummaryService
from app.services.customer_summary_delivery_service import (
    CustomerSummaryDeliveryProvider,
    CustomerSummaryDeliveryService,
)
from app.services.customer_summary_message_service import CustomerSummaryMessageService
from app.messaging.sms_gate_provider import SmsGateDeliveryProvider
from app.services.customer_summary_repository import CustomerSummaryDeliveryRepository
from app.services.post_call_summary_repository import PostCallSummaryRepository
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
    ComponentLearning,
    RuntimeImprovementService,
)
from app.domain.learning_evidence import LearningComponent

def build_post_call_summary_service(
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
) -> PostCallSummaryService:
    return PostCallSummaryService(
        create_summary_provider(llm_client=llm_client, settings=settings)
    )


class NullCustomerSummaryDeliveryProvider(CustomerSummaryDeliveryProvider):
    """"noop": records each delivery as sent without sending it (demos
    and tests)."""

    def send_summary(
        self,
        contact: CustomerContact,
        message: str,
        channel: MessagingChannel,
    ) -> str:
        return f"noop-{uuid4()}"


class DisabledCustomerSummaryDeliveryProvider(NullCustomerSummaryDeliveryProvider):
    """No delivery provider is set up: nothing is sent, and deliveries
    are recorded as not sent."""

    delivers = False


DISABLED_DELIVERY_PROVIDERS = frozenset({"disabled", "none", "null"})


def create_customer_summary_delivery_provider(
    settings: Settings | None = None,
) -> CustomerSummaryDeliveryProvider:
    settings = settings or Settings()
    provider_name = settings.customer_summary_delivery_provider.strip().lower()
    if provider_name in DISABLED_DELIVERY_PROVIDERS:
        return DisabledCustomerSummaryDeliveryProvider()
    if provider_name == "noop":
        return NullCustomerSummaryDeliveryProvider()
    if provider_name == "sms_gate":
        return SmsGateDeliveryProvider(
            url=settings.sms_gate_url,
            username=settings.sms_gate_username,
            password=settings.sms_gate_password,
            timeout_seconds=settings.customer_summary_sms_timeout_seconds,
            retry_attempts=settings.customer_summary_sms_retry_attempts,
            sim_number=settings.sms_gate_sim_number,
            ttl_seconds=settings.sms_gate_ttl_seconds,
        )
    raise ValueError(
        f"Unsupported customer summary delivery provider: {provider_name!r}. "
        "Configure customer_summary_delivery_provider to one of: disabled, noop, sms_gate."
    )


def build_customer_summary_delivery_service(
    settings: Settings | None = None,
    provider: CustomerSummaryDeliveryProvider | None = None,
    repository: CustomerSummaryDeliveryRepository | None = None,
) -> CustomerSummaryDeliveryService:
    settings = settings or Settings()
    provider = provider or create_customer_summary_delivery_provider(settings)
    return CustomerSummaryDeliveryService(
        provider=provider,
        message_service=CustomerSummaryMessageService(
            default_channel=MessagingChannel(settings.customer_summary_default_channel),
            sms_max_parts=settings.customer_summary_sms_max_parts,
        ),
        repository=repository,
        require_consent=settings.customer_summary_consent_required,
        max_attempts=settings.customer_summary_max_attempts,
    )


def build_conversation_repository() -> ConversationRepository:
    return InMemoryConversationRepository()


def build_coverage_repository(
    settings: Settings | None = None,
) -> ConversationCoverageRepository:
    return create_coverage_repository(settings)

def build_estimation_service(
    provider: ServiceEstimationProvider | None = None,
    *,
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
    pricing: PricingSource | None = None,
) -> EstimationService:
    # The price list in use (PriceListService.pricing), else the sample one.
    pricing = pricing or DEFAULT_PRICING_CONFIG
    provider = provider or RuleBasedEstimationProvider(pricing)
    detector: ServiceDetectionProvider = KeywordServiceDetector(pricing)
    name = (settings.estimation_provider if settings is not None else "rule_based").strip().lower()
    if name == "llm" and llm_client is not None:
        detector = LLMServiceDetector(llm_client, pricing, fallback=detector)
    elif name not in ("llm", "rule_based"):
        raise UnsupportedProviderError(
            f"Unsupported estimation provider: {name!r}. Available: ['llm', 'rule_based']."
        )
    return EstimationService(provider, pricing, detector)

def build_call_service(repository: ConversationRepository | None = None) -> CallService:
    return CallService(ConversationService(repository or build_conversation_repository()))


def build_next_question_service(
    provider: QuestionSuggestionProvider,
    runtime_improvement_service: RuntimeImprovementService | None = None,
    improvement_usage_recorder: ImprovementEffectivenessService | None = None,
    category_descriptions: Callable[[], Mapping[str, str | None]] | None = None,
    settings: Settings | None = None,
) -> NextQuestionService:
    settings = settings or Settings()
    return NextQuestionService(
        provider=provider,
        runtime_improvement_service=runtime_improvement_service,
        improvement_usage_recorder=improvement_usage_recorder,
        category_descriptions=category_descriptions,
        limit=settings.question_suggestion_limit,
        in_live_analysis=settings.live_questions_in_analysis,
    )

def build_conversation_analysis_service(
    complaint_provider: ComplaintDetectionProvider,
    sentiment_provider: SentimentAnalysisProvider,
    runtime_improvement_service: RuntimeImprovementService | None = None,
    improvement_usage_recorder: ImprovementEffectivenessService | None = None,
    live_analyzer: LLMLiveAnalysisProvider | None = None,
) -> ConversationAnalysisService:
    def learning_for(component: LearningComponent) -> ComponentLearning | None:
        if runtime_improvement_service is None:
            return None
        return ComponentLearning(
            component, runtime_improvement_service, improvement_usage_recorder
        )

    return ConversationAnalysisService(
        complaint_service=ComplaintAnalysisService(
            complaint_provider, learning_for(LearningComponent.COMPLAINT_DETECTION)
        ),
        sentiment_service=SentimentAnalysisService(
            sentiment_provider, learning_for(LearningComponent.SENTIMENT_ANALYSIS)
        ),
        live_analyzer=live_analyzer,
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
    post_call_summary_repository: PostCallSummaryRepository | None = None,
    runtime_improvement_service: RuntimeImprovementService | None = None,
    improvement_usage_recorder: ImprovementEffectivenessService | None = None,
    *,
    complaint_provider: ComplaintDetectionProvider | None = None,
    sentiment_provider: SentimentAnalysisProvider | None = None,
    question_provider: QuestionSuggestionProvider | None = None,
    live_analyzer: LLMLiveAnalysisProvider | None = None,
    category_descriptions: Callable[[], Mapping[str, str | None]] | None = None,
    escalation_service: EscalationService | None = None,
    complaint_lifecycle_service: ComplaintLifecycleService | None = None,
    customer_id_resolver: Callable[[str], str | None] | None = None,
    emerging_complaint_service: EmergingComplaintService | None = None,
    emerging_complaint_auto_discovery: bool = False,
    live_state_store: LiveStateStore | None = None,
    live_analysis_ttl_seconds: float = DEFAULT_LIVE_ANALYSIS_TTL_SECONDS,
    transcript_reviser: Callable[[Conversation], tuple[Utterance, ...] | None] | None = None,
    vehicle_model_resolver: Callable[[str], str | None] | None = None,
    alert_service: CallAlertService | None = None,
    handled_questions: Callable[[str], tuple[str, ...]] | None = None,
    indicators: CallIndicators | None = None,
) -> CallWorkflowService:
    """The one place the call workflow is put together.

    The application (app.api.wiring) passes its AI providers and every
    collaborator. A caller that passes less gets a smaller system: AI
    providers made from llm_client (or the configured LLM), in-memory
    stores, and none of the optional parts (escalation, complaint
    tracking, customer lookups, re-transcription). That is what the
    audio-file runner in scripts/ uses."""
    needs_llm = (
        complaint_provider is None
        or sentiment_provider is None
        or question_provider is None
        or estimation_service is None
        or post_call_summary_service is None
    )
    if llm_client is None and needs_llm:
        llm_client = create_llm_client(settings)

    return CallWorkflowService(
        call_service=call_service or build_call_service(),
        coverage_repository=coverage_repository or build_coverage_repository(settings),
        analysis_service=build_conversation_analysis_service(
            complaint_provider=(
                create_complaint_provider(llm_client)
                if complaint_provider is None
                else complaint_provider
            ),
            sentiment_provider=(
                create_sentiment_provider(llm_client)
                if sentiment_provider is None
                else sentiment_provider
            ),
            runtime_improvement_service=runtime_improvement_service,
            improvement_usage_recorder=improvement_usage_recorder,
            live_analyzer=live_analyzer,
        ),
        next_question_service=build_next_question_service(
            provider=(
                create_question_provider(llm_client)
                if question_provider is None
                else question_provider
            ),
            runtime_improvement_service=runtime_improvement_service,
            improvement_usage_recorder=improvement_usage_recorder,
            category_descriptions=category_descriptions,
            settings=settings,
        ),
        estimation_service=estimation_service
        or build_estimation_service(settings=settings, llm_client=llm_client),
        post_call_summary_service=post_call_summary_service
        or build_post_call_summary_service(settings=settings, llm_client=llm_client),
        customer_summary_delivery_service=customer_summary_delivery_service,
        customer_contact_resolver=customer_contact_resolver,
        learning_recorder=learning_recorder,
        post_call_summary_repository=post_call_summary_repository,
        customer_summary_enabled=(settings or Settings()).customer_summary_enabled,
        escalation_service=escalation_service,
        complaint_lifecycle_service=complaint_lifecycle_service,
        customer_id_resolver=customer_id_resolver,
        emerging_complaint_service=emerging_complaint_service,
        emerging_complaint_auto_discovery=emerging_complaint_auto_discovery,
        live_state_store=live_state_store,
        live_analysis_ttl_seconds=live_analysis_ttl_seconds,
        transcript_reviser=transcript_reviser,
        vehicle_model_resolver=vehicle_model_resolver,
        alert_service=alert_service,
        handled_questions=handled_questions,
        indicators=indicators,
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
        language_lock=LanguageLock(
            lock_after=(settings or Settings()).asr_language_lock_after,
            unlock_after=(settings or Settings()).asr_language_unlock_after,
        ),
    )