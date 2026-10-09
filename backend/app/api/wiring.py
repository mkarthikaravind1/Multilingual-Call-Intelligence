import logging
from collections.abc import Callable

from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider
from app.api.dependencies import ApiServices
from app.composition.live_processing import build_live_chunk_processing_service
from app.services.call_recording_store import CallRecordingStore
from app.services.post_call_retranscription import PostCallRetranscriptionService
from app.composition.services import (
    build_customer_summary_delivery_service,
    build_estimation_service,
    build_post_call_summary_service,
)
from app.composition.providers import (
    create_asr_provider,
    create_call_mapping_repository,
    create_language_provider,
    create_llm_client,
    create_telephony_provider,
    warm_up_diarization,
)
from app.core.config import Settings, get_settings
from app.composition.speaker_sessions import build_speaker_session_registry
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.customer_summary_delivery_service import CustomerSummaryDeliveryService
from app.services.customer_summary_repository import (
    CustomerSummaryDeliveryRepository,
    InMemoryCustomerSummaryDeliveryRepository,
)
from app.services.post_call_summary_repository import (
    InMemoryPostCallSummaryRepository,
    PostCallSummaryRepository,
)
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
from app.domain.learning_evidence import LearningComponent
from app.domain.learning_feedback_repository import (
    InMemoryLearningFeedbackRepository,
    LearningFeedbackRepository,
)
from app.services.runtime_improvement_service import ComponentLearning
from app.composition.providers import create_customer_directory
from app.crm.provider import CustomerDirectory, NoCustomerDirectory
from app.services.call_customer_repository import (
    CallCustomerRepository,
    InMemoryCallCustomerRepository,
)
from app.services.call_customer_service import CallCustomerService
from app.ai.escalation.provider import EscalationDetectionProvider
from app.ai.escalation.rule_based_provider import RuleBasedEscalationProvider
from app.composition.providers import create_escalation_provider
from app.services.escalation_repository import (
    EscalationRepository,
    InMemoryEscalationRepository,
)
from app.services.escalation_service import EscalationService
from app.domain.user_repository import InMemoryUserRepository, UserRepository
from app.ai.emerging_complaint.provider import EmergingComplaintDiscoveryProvider
from app.ai.emerging_complaint.rule_based_provider import (
    RuleBasedEmergingComplaintDiscoveryProvider,
)
from app.composition.providers import create_emerging_complaint_provider
from app.domain.complaint_lifecycle_repository import (
    ComplaintLifecycleRepository,
    InMemoryComplaintLifecycleRepository,
)
from app.services.complaint_lifecycle_service import ComplaintLifecycleService
from app.services.call_listing import CallListingQuery, InMemoryCallListingQuery
from app.services.emerging_complaint_repository import (
    EmergingComplaintRepository,
    InMemoryEmergingComplaintRepository,
)
from app.services.emerging_complaint_service import EmergingComplaintService
from app.composition.providers import create_live_state_store
from app.domain.conversation import ConversationStatus
from app.observability.metrics import REGISTRY, Gauge
from app.services.background_jobs import BackgroundJobRunner, PeriodicJob
from app.services.live_analysis_scheduler import LiveAnalysisScheduler
from app.services.live_state_store import InMemoryLiveStateStore, LiveStateStore
from app.services.post_call_repair_service import PostCallRepairService
from app.services.user_management_service import UserManagementService
from app.services.auth_service import AuthService
from app.services.price_list_repository import (
    InMemoryPriceListRepository,
    PriceListRepository,
)
from app.services.price_list_service import PriceListService
from app.services.complaint_category_catalog import ComplaintCategoryCatalog

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
    feedback_repository: LearningFeedbackRepository | None = None,
    user_repository: UserRepository | None = None,
    customer_contact_resolver: Callable[[str], CustomerContact | None] | None = None,
    post_call_summary_repository: PostCallSummaryRepository | None = None,
    customer_summary_delivery_repository: CustomerSummaryDeliveryRepository | None = None,
    call_customer_repository: CallCustomerRepository | None = None,
    customer_directory: CustomerDirectory | None = None,
    escalation_repository: EscalationRepository | None = None,
    escalation_provider: EscalationDetectionProvider | None = None,
    complaint_lifecycle_repository: ComplaintLifecycleRepository | None = None,
    emerging_complaint_repository: EmergingComplaintRepository | None = None,
    emerging_complaint_provider: EmergingComplaintDiscoveryProvider | None = None,
    complaint_category_catalog: ComplaintCategoryCatalog | None = None,
    live_state_store: LiveStateStore | None = None,
    call_listing_query: CallListingQuery | None = None,
    price_list_repository: PriceListRepository | None = None,
) -> ApiServices:

    """Build the services the live application uses.

    Every repository is injectable so the composition root (main.py) can
    pass PostgreSQL-backed repositories in production while tests keep
    getting the in-memory defaults below.
    """
    settings = settings or get_settings()

    # --- Live state shared between API instances ---
    shared_live_state = live_state_store is not None
    if live_state_store is None:
        try:
            live_state_store = create_live_state_store(settings)
            shared_live_state = settings.live_state_store_provider.strip().lower() != "in_memory"
        except Exception as exc:
            if settings.is_production:
                raise
            logger.error("Live state store unavailable, keeping it in memory: %s", exc)
            live_state_store = InMemoryLiveStateStore()

    post_call_summary_repository = (
        post_call_summary_repository or InMemoryPostCallSummaryRepository()
    )
    conversation_repository = conversation_repository or InMemoryConversationRepository()
    coverage_repository = coverage_repository or InMemoryConversationCoverageRepository()
    evidence_repository = evidence_repository or InMemoryLearningEvidenceRepository()
    observation_repository = observation_repository or InMemoryLearningObservationRepository()
    candidate_repository = candidate_repository or InMemoryImprovementCandidateRepository()
    active_improvement_repository = (
        active_improvement_repository or InMemoryActiveImprovementRepository()
    )
    usage_repository = usage_repository or InMemoryImprovementUsageRepository()
    feedback_repository = feedback_repository or InMemoryLearningFeedbackRepository()

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
    user_management_service = UserManagementService(user_repository, auth_service)
    try:
        user_management_service.bootstrap_admin(
            settings.bootstrap_admin_email, settings.bootstrap_admin_password
        )
    except Exception:
        logger.exception("Could not bootstrap the first admin user")

    # --- Caller identity and the CRM boundary ---
    if customer_directory is None:
        try:
            customer_directory = create_customer_directory(settings)
        except Exception as exc:
            logger.error("CRM is not available; customers will not be identified: %s", exc)
            customer_directory = NoCustomerDirectory()
    call_customer_repository = call_customer_repository or InMemoryCallCustomerRepository()
    call_customer_service = CallCustomerService(
        call_customer_repository,
        customer_directory,
        default_country_code=settings.phone_default_country_code,
    )
    if customer_contact_resolver is None:
        customer_contact_resolver = call_customer_service.resolve_contact

    # --- The service centre's price list (what estimates are priced with) ---
    price_list_service = PriceListService(
        price_list_repository or InMemoryPriceListRepository(),
        cache_seconds=settings.price_list_cache_seconds,
    )

    # --- Escalation intelligence ---
    if escalation_provider is None:
        try:
            escalation_provider = create_escalation_provider(settings=settings)
        except Exception as exc:
            logger.warning("Falling back to rule-based escalation detection: %s", exc)
            escalation_provider = RuleBasedEscalationProvider()
    escalation_repository = escalation_repository or InMemoryEscalationRepository()
    escalation_service = EscalationService(escalation_repository, escalation_provider)

    # --- Complaint lifecycle and emerging complaints ---
    complaint_lifecycle_repository = (
        complaint_lifecycle_repository or InMemoryComplaintLifecycleRepository()
    )
    complaint_lifecycle_service = ComplaintLifecycleService(complaint_lifecycle_repository)

    # --- The browsable call list (a read model over the stores above) ---
    if call_listing_query is None:
        call_listing_query = InMemoryCallListingQuery(
            conversation_repository,
            call_customer_repository,
            escalation_repository,
            complaint_lifecycle_repository,
        )
    if emerging_complaint_provider is None:
        try:
            emerging_complaint_provider = create_emerging_complaint_provider(settings=settings)
        except Exception as exc:
            logger.warning("Falling back to rule-based emerging-complaint discovery: %s", exc)
            emerging_complaint_provider = RuleBasedEmergingComplaintDiscoveryProvider()
    emerging_complaint_repository = (
        emerging_complaint_repository or InMemoryEmergingComplaintRepository()
    )
    # Built-in categories plus accepted themes. Pass the catalog the
    # complaint provider uses (main.py does) so an accept reaches it at once.
    if complaint_category_catalog is None:
        complaint_category_catalog = ComplaintCategoryCatalog(
            emerging_complaint_repository,
            cache_seconds=settings.complaint_category_cache_seconds,
        )
    emerging_complaint_service = EmergingComplaintService(
        emerging_complaint_repository,
        emerging_complaint_provider,
        call_service,
        coverage_repository,
        max_calls=settings.emerging_complaint_discovery_max_calls,
        store=live_state_store,
        min_interval_seconds=settings.emerging_complaint_discovery_min_interval_seconds,
        catalog=complaint_category_catalog,
    )

    try:
        customer_summary_delivery_service = build_customer_summary_delivery_service(
            settings=settings,
            repository=customer_summary_delivery_repository
            or InMemoryCustomerSummaryDeliveryRepository(),
        )
    except Exception as exc:
        logger.warning("Customer summary delivery is not available: %s", exc)
        customer_summary_delivery_service = None

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

    # --- Post-call re-transcription (from the call's recorded audio) ---
    call_recording_store = None
    transcript_reviser = None
    if (
        settings.post_call_retranscription_enabled
        and asr_provider is not None
        and language_provider is not None
    ):
        call_recording_store = CallRecordingStore(
            max_calls=settings.call_recording_max_calls,
            ttl_seconds=settings.post_call_repair_min_age_seconds + 3600.0,
        )
        transcript_reviser = PostCallRetranscriptionService(
            asr_provider,
            language_provider,
            call_recording_store,
            window_seconds=settings.post_call_retranscription_window_seconds,
            workers=settings.post_call_retranscription_workers,
            silence_rms=settings.plivo_stream_silence_rms,
        ).retranscribe

    workflow_service = CallWorkflowService(
        call_service,
        coverage_repository,
        ConversationAnalysisService(
            ComplaintAnalysisService(
                complaint_provider,
                ComponentLearning(
                    LearningComponent.COMPLAINT_DETECTION,
                    runtime_improvement_service,
                    improvement_effectiveness_service,
                ),
            ),
            SentimentAnalysisService(
                sentiment_provider,
                ComponentLearning(
                    LearningComponent.SENTIMENT_ANALYSIS,
                    runtime_improvement_service,
                    improvement_effectiveness_service,
                ),
            ),
        ),
        NextQuestionService(
            provider=question_provider,
            runtime_improvement_service=runtime_improvement_service,
            improvement_usage_recorder=improvement_effectiveness_service,
        ),
        _build_estimation_service(settings, price_list_service),
        build_post_call_summary_service(),
        customer_summary_delivery_service=customer_summary_delivery_service,
        customer_contact_resolver=customer_contact_resolver,
        learning_recorder=build_learning_call_recorder(
            evidence_repository=evidence_repository,
            observation_repository=observation_repository,
        ),
        post_call_summary_repository=post_call_summary_repository,
        customer_summary_enabled=settings.customer_summary_enabled,
        escalation_service=escalation_service,
        complaint_lifecycle_service=complaint_lifecycle_service,
        customer_id_resolver=call_customer_service.resolve_customer_id,
        emerging_complaint_service=emerging_complaint_service,
        emerging_complaint_auto_discovery=settings.emerging_complaint_auto_discovery,
        live_state_store=live_state_store,
        live_analysis_ttl_seconds=settings.live_analysis_ttl_seconds,
        transcript_reviser=transcript_reviser,
        vehicle_model_resolver=call_customer_service.resolve_vehicle_model,
    )

    # --- Post-call repair ---
    post_call_repair_service = PostCallRepairService(
        call_service,
        workflow_service.process_completed_call,
        post_call_summary_repository,
        live_state_store,
        min_age_seconds=settings.post_call_repair_min_age_seconds,
        max_attempts=settings.post_call_repair_max_attempts,
        scan_limit=settings.post_call_repair_scan_limit,
        background_interval_seconds=settings.post_call_repair_interval_seconds,
    )
    background_jobs = BackgroundJobRunner(
        [
            PeriodicJob(
                "post_call_repair",
                settings.post_call_repair_interval_seconds,
                post_call_repair_service.run,
            )
        ]
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

    telephony_call_service = TelephonyCallService(
        call_service,
        call_mapping_repository,
        call_customer_service=call_customer_service,
        live_state=live_state_store,
    )

    try:
        telephony_provider = create_telephony_provider(settings)
    except Exception as exc:
        logger.warning("Telephony provider is not available: %s", exc)
        telephony_provider = None

    live_chunk_processing_service = None
    if asr_provider is not None and language_provider is not None:
        try:
            live_chunk_processing_service = build_live_chunk_processing_service(
                # Speech is stored and shown as soon as it is transcribed;
                # the AI analysis follows in the background (see
                # LiveAnalysisScheduler), so it never delays the next chunk.
                workflow_service=LiveAnalysisScheduler(
                    workflow_service,
                    min_interval_seconds=settings.live_analysis_min_interval_seconds,
                ),
                diarization_segments=(),
                settings=settings,
                asr_provider=asr_provider,
                language_provider=language_provider,
                registry=build_speaker_session_registry(
                    live_state_store if shared_live_state else None
                ),
            )
        except Exception as exc:
            logger.warning("Live chunk processing is not available: %s", exc)

    def warm_up_live_models() -> None:
        try:
            warm_up_diarization(settings)
        except Exception as exc:
            logger.warning("Diarization model could not be preloaded: %s", exc)
            live_chunk_processing_service = None

    _register_domain_gauges(
        call_service, escalation_service, complaint_lifecycle_service, post_call_repair_service
    )

    services = ApiServices(
        call_service=call_service,
        call_listing=call_listing_query,
        workflow_service=workflow_service,
        learning=learning_service
        or build_learning_management_service(
            evidence_repository=evidence_repository,
            candidate_repository=candidate_repository,
            observation_repository=observation_repository,
            feedback_repository=feedback_repository,
            active_improvement_repository=active_improvement_repository,
            usage_repository=usage_repository,
            complaint_categories=complaint_category_catalog.names,
        ),
        auth=auth_service,
        user_repository=user_repository,
        telephony_provider=telephony_provider,
        telephony_call_service=telephony_call_service,
        live_chunk_processing_service=live_chunk_processing_service,
        customer_summary_delivery_service=customer_summary_delivery_service,
        asr_provider=asr_provider,
        telephony_stream_flush_seconds=settings.plivo_stream_flush_seconds,
        call_recording_store=call_recording_store,
        call_customer_service=call_customer_service,
        customer_summary_enabled=settings.customer_summary_enabled,
        escalation_service=escalation_service,
        complaint_lifecycle_service=complaint_lifecycle_service,
        emerging_complaint_service=emerging_complaint_service,
        live_state_store=live_state_store,
        live_call_push_interval_seconds=settings.live_call_push_interval_seconds,
        post_call_repair_service=post_call_repair_service,
        user_management_service=user_management_service,
        price_list_service=price_list_service,
        complaint_category_catalog=complaint_category_catalog,
        background_jobs=background_jobs,
        warm_up=warm_up_live_models if live_chunk_processing_service is not None else None,
        health_checks={"live_state": live_state_store.ping} if shared_live_state else {},
    )
    REGISTRY.register(
        Gauge(
            "dependency_up",
            "1 when a dependency this instance needs answers (see /health/ready), else 0.",
            ("dependency",),
            lambda: _dependency_status(services.health_checks),
        )
    )
    return services


def _build_estimation_service(settings: Settings, price_list_service: PriceListService):
    llm_client = None
    if settings.estimation_provider.strip().lower() == "llm":
        try:
            llm_client = create_llm_client(settings)
        except Exception as exc:
            logger.warning("Service estimates will use the price-list keywords only: %s", exc)
    return build_estimation_service(
        settings=settings, llm_client=llm_client, pricing=price_list_service.pricing
    )


def _dependency_status(checks) -> dict[tuple[str, ...], float]:
    status: dict[tuple[str, ...], float] = {}
    for name, check in (checks or {}).items():
        try:
            check()
            status[(name,)] = 1.0
        except Exception:
            status[(name,)] = 0.0
    return status


def _register_domain_gauges(
    call_service: CallService,
    escalation_service: EscalationService,
    complaint_lifecycle_service: ComplaintLifecycleService,
    post_call_repair_service: PostCallRepairService,
) -> None:
    """Gauges read from stored data when /metrics is scraped."""

    def calls_by_status():
        counts = call_service.count_calls_by_status()
        return {(status.value,): float(counts.get(status, 0)) for status in ConversationStatus}

    def open_escalations():
        queue = escalation_service.list_queue(active=True)
        levels: dict[tuple[str, ...], float] = {}
        for escalation in queue:
            key = (escalation.level.value,)
            levels[key] = levels.get(key, 0.0) + 1
        return levels

    def open_complaints():
        views = complaint_lifecycle_service.list_queue("open", limit=100_000)
        follow_up = sum(1 for v in views if v.record.follow_up_required)
        return {("follow_up",): float(follow_up), ("other",): float(len(views) - follow_up)}

    def unprocessed_calls():
        run = post_call_repair_service.last_run
        return {(): float(0 if run is None else run.pending)}

    for gauge in (
        Gauge("calls", "Calls by status.", ("status",), calls_by_status),
        Gauge("escalations_open", "Open escalations by level.", ("level",), open_escalations),
        Gauge("complaints_open", "Open complaints, by whether they need follow-up.", ("kind",), open_complaints),
        Gauge(
            "post_call_unprocessed_calls",
            "Completed calls without a post-call summary at the last repair sweep.",
            (),
            unprocessed_calls,
        ),
    ):
        REGISTRY.register(gauge)
