import logging
from collections.abc import Callable

from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider
from app.api.dependencies import ApiServices
from app.composition.live_processing import build_live_chunk_processing_service
from app.composition.services import (
    build_customer_summary_delivery_service,
    build_estimation_service,
    build_post_call_summary_service,
)
from app.composition.providers import (
    create_asr_provider,
    create_call_mapping_repository,
    create_language_provider,
    create_telephony_provider,
)
from app.core.config import Settings, get_settings
from app.composition.speaker_sessions import build_speaker_session_registry
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.customer_summary_delivery_service import CustomerSummaryDeliveryService
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
from app.services.telephony_call_service import TelephonyCallService
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
from app.domain.customer_contact import CustomerContact
from app.domain.user_repository import InMemoryUserRepository, UserRepository
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)


def build_api_services(
    complaint_provider: ComplaintDetectionProvider,
    sentiment_provider: SentimentAnalysisProvider,
    question_provider: QuestionSuggestionProvider,
    settings: Settings | None = None,
    learning_service: LearningManagementService | None = None,
    conversation_repository: ConversationRepository | None = None,
    coverage_repository: ConversationCoverageRepository | None = None,
    evidence_repository: LearningEvidenceRepository | None = None,
    observation_repository: LearningObservationRepository | None = None,
    candidate_repository: ImprovementCandidateRepository | None = None,
    active_improvement_repository: ActiveImprovementRepository | None = None,
    usage_repository: ImprovementUsageRepository | None = None,
    user_repository: UserRepository | None = None,
    customer_contact_resolver: Callable[[str], CustomerContact | None] | None = None,
) -> ApiServices:

    """Build the services the live application uses.

    Every repository is injectable so the composition root (main.py) can
    pass PostgreSQL-backed repositories in production while tests keep
    getting the in-memory defaults below.
    """
    settings = settings or get_settings()

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

    user_repository = user_repository or InMemoryUserRepository()
    auth_service = AuthService(user_repository)

    try:
        customer_summary_delivery_service = build_customer_summary_delivery_service(
            settings=settings
        )
    except Exception as exc:
        logger.warning("Customer summary delivery is not available: %s", exc)
        customer_summary_delivery_service = None

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
        customer_summary_delivery_service=customer_summary_delivery_service,
        customer_contact_resolver=customer_contact_resolver,
        learning_recorder=build_learning_call_recorder(
            evidence_repository=evidence_repository,
            observation_repository=observation_repository,
        ),
    )

    # --- Telephony (Production Telephony) ---
    # Each piece degrades to None/in-memory independently, so an
    # unconfigured provider never prevents the rest of the app (learning,
    # auth, the manual /live endpoint) from starting.
    try:
        call_mapping_repository = create_call_mapping_repository(settings)
    except Exception as exc:
        logger.warning("Falling back to in-memory call mapping store: %s", exc)
        from app.services.telephony_call_mapping_repository import (
            InMemoryTelephonyCallMappingRepository,
        )

        call_mapping_repository = InMemoryTelephonyCallMappingRepository()

    telephony_call_service = TelephonyCallService(call_service, call_mapping_repository)

    try:
        telephony_provider = create_telephony_provider(settings)
    except Exception as exc:
        logger.warning("Telephony provider is not available: %s", exc)
        telephony_provider = None

    try:
        asr_provider = create_asr_provider(settings)
    except Exception as exc:
        logger.warning("ASR provider is not available: %s", exc)
        asr_provider = None

    try:
        language_provider = create_language_provider(settings)
    except Exception as exc:
        logger.warning("Language provider is not available: %s", exc)
        language_provider = None

    live_chunk_processing_service = None
    if asr_provider is not None and language_provider is not None:
        try:
            live_chunk_processing_service = build_live_chunk_processing_service(
                workflow_service=workflow_service,
                diarization_segments=(),
                settings=settings,
                asr_provider=asr_provider,
                language_provider=language_provider,
                registry=build_speaker_session_registry(),
            )
        except Exception as exc:
            logger.warning("Live chunk processing is not available: %s", exc)
            live_chunk_processing_service = None

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
        telephony_provider=telephony_provider,
        telephony_call_service=telephony_call_service,
        live_chunk_processing_service=live_chunk_processing_service,
        customer_summary_delivery_service=customer_summary_delivery_service,
        asr_provider=asr_provider,
        telephony_stream_flush_seconds=settings.plivo_stream_flush_seconds,
    )