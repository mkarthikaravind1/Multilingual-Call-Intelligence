import logging
from collections.abc import Callable
from typing import TypeVar

from app.ai.complaint.llm_provider import LLMComplaintProvider
from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.escalation.llm_provider import HybridEscalationProvider
from app.ai.live_analysis.llm_provider import LLMLiveAnalysisProvider
from app.ai.sentiment.llm_provider import LLMSentimentProvider
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider
from app.api.dependencies import ApiServices
from app.composition.live_processing import build_live_chunk_processing_service
from app.services.call_recording_store import CallRecordingStore
from app.services.post_call_retranscription import PostCallRetranscriptionService
from app.composition.services import (
    build_call_workflow_service,
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
from app.services.customer_summary_delivery_service import CustomerSummaryDeliveryService
from app.services.customer_summary_repository import (
    CustomerSummaryDeliveryRepository,
    InMemoryCustomerSummaryDeliveryRepository,
)
from app.services.post_call_summary_repository import (
    InMemoryPostCallSummaryRepository,
    PostCallSummaryRepository,
)
from app.services.conversation_coverage_repository import ConversationCoverageRepository
from app.services.conversation_repository import ConversationRepository
from app.services.conversation_service import ConversationService
from app.services.in_memory_conversation_coverage_repository import (
    InMemoryConversationCoverageRepository,
)
from app.services.in_memory_conversation_repository import (
    InMemoryConversationRepository,
)
from app.services.telephony_call_mapping_repository import (
    InMemoryTelephonyCallMappingRepository,
)
from app.services.telephony_call_service import TelephonyCallService
from app.composition.learning import build_learning_management_service
from app.services.learning_management_service import LearningManagementService
from app.services.pattern_discovery_service import PatternRules
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
from app.domain.learning_feedback_repository import (
    InMemoryLearningFeedbackRepository,
    LearningFeedbackRepository,
)
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
from app.services.call_indicators import CallIndicators
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
from app.services.live_analysis_store import LiveAnalysisStore
from app.services.live_calls import LiveAlertSweeper, LiveCallsBoard
from app.services.live_state_store import InMemoryLiveStateStore, LiveStateStore
from app.services.post_call_repair_service import PostCallRepairService
from app.services.stale_call_service import StaleCallSweeper
from app.services.user_management_service import UserManagementService
from app.services.auth_service import AuthService
from app.services.price_list_repository import (
    InMemoryPriceListRepository,
    PriceListRepository,
)
from app.services.price_list_service import PriceListService
from app.services.login_throttle import LoginLimits, LoginThrottle
from app.services.complaint_category_catalog import ComplaintCategoryCatalog
from app.domain.location import InMemoryLocationRepository, LocationRepository
from app.services.call_routing_service import CallRoutingService
from app.services.location_service import LocationService
from app.services.recording_archive import RecordingArchive, RecordingRepository
from app.services.call_alerts import (
    AlertRules,
    CallAlertRepository,
    CallAlertService,
    InMemoryCallAlertRepository,
    InMemoryQuestionOutcomeRepository,
    QuestionOutcomeRepository,
)
from app.services.performance import PerformanceService
from app.services.reporting import (
    MAX_REPORT_CALLS,
    InMemoryReportSource,
    ReportService,
    ReportSource,
)

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


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
    location_repository: LocationRepository | None = None,
    report_source: ReportSource | None = None,
    call_alert_repository: CallAlertRepository | None = None,
    question_outcome_repository: QuestionOutcomeRepository | None = None,
    recording_repository: RecordingRepository | None = None,
) -> ApiServices:

    """Build the services the live application uses.

    Every repository is injectable so the composition root (main.py) can
    pass PostgreSQL-backed repositories in production while tests keep
    getting the in-memory defaults below.
    """
    settings = settings or get_settings()
    live_state_store, shared_live_state = _live_state(settings, live_state_store)

    # --- Stores: the ones passed in, else in memory ---
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
    user_repository = user_repository or InMemoryUserRepository()
    call_customer_repository = call_customer_repository or InMemoryCallCustomerRepository()
    escalation_repository = escalation_repository or InMemoryEscalationRepository()
    complaint_lifecycle_repository = (
        complaint_lifecycle_repository or InMemoryComplaintLifecycleRepository()
    )
    emerging_complaint_repository = (
        emerging_complaint_repository or InMemoryEmergingComplaintRepository()
    )

    location_repository = location_repository or InMemoryLocationRepository()
    question_outcome_repository = (
        question_outcome_repository or InMemoryQuestionOutcomeRepository()
    )
    # --- On-screen alerts on live calls ---
    alert_service = CallAlertService(
        call_alert_repository or InMemoryCallAlertRepository(),
        live_state_store,
        AlertRules.from_settings(settings),
    )

    call_service = CallService(ConversationService(conversation_repository))
    auth_service, user_management_service = _build_user_services(
        settings, user_repository, location_repository
    )
    # --- Where calls are taken, and by whom ---
    location_service = LocationService(
        location_repository,
        user_repository,
        default_country_code=settings.phone_default_country_code,
    )
    call_routing = CallRoutingService(
        location_repository,
        user_repository,
        default_country_code=settings.phone_default_country_code,
    )

    # --- Caller identity and the CRM boundary ---
    call_customer_service = CallCustomerService(
        call_customer_repository,
        _customer_directory(settings, customer_directory),
        default_country_code=settings.phone_default_country_code,
    )
    if customer_contact_resolver is None:
        customer_contact_resolver = call_customer_service.resolve_contact_for_delivery

    # --- The service centre's price list (what estimates are priced with) ---
    price_list_service = PriceListService(
        price_list_repository or InMemoryPriceListRepository(),
        cache_seconds=settings.price_list_cache_seconds,
    )

    # --- Escalation, complaint lifecycle and emerging complaints ---
    if escalation_provider is None:
        escalation_provider = _built_or(
            RuleBasedEscalationProvider,
            lambda: create_escalation_provider(settings=settings),
            "Falling back to rule-based escalation detection",
        )
    escalation_service = EscalationService(escalation_repository, escalation_provider)
    complaint_lifecycle_service = ComplaintLifecycleService(complaint_lifecycle_repository)
    # Built-in categories plus accepted themes. Pass the catalog the
    # complaint provider uses (main.py does) so an accept reaches it at once.
    if complaint_category_catalog is None:
        complaint_category_catalog = ComplaintCategoryCatalog(
            emerging_complaint_repository,
            cache_seconds=settings.complaint_category_cache_seconds,
        )
    emerging_complaint_service = _build_emerging_complaint_service(
        settings,
        emerging_complaint_repository,
        emerging_complaint_provider,
        call_service,
        coverage_repository,
        live_state_store,
        complaint_category_catalog,
    )

    # --- The browsable call list (a read model over the stores above) ---
    if call_listing_query is None:
        call_listing_query = InMemoryCallListingQuery(
            conversation_repository,
            call_customer_repository,
            escalation_repository,
            complaint_lifecycle_repository,
            location_repository,
            user_repository,
        )

    # --- Reports (another read model over the same stores) ---
    report_service = ReportService(
        report_source
        or InMemoryReportSource(
            conversation_repository,
            coverage_repository,
            post_call_summary_repository,
            location_repository,
            user_repository,
            complaint_lifecycle_repository,
            call_customer_repository,
            escalation_repository,
            question_outcome_repository,
        ),
        location_repository,
        user_repository,
    )
    performance_service = PerformanceService(report_service.source, max_calls=MAX_REPORT_CALLS)

    # --- Parts that are simply absent when not configured ---
    customer_summary_delivery_service = _optional(
        lambda: build_customer_summary_delivery_service(
            settings=settings,
            repository=customer_summary_delivery_repository
            or InMemoryCustomerSummaryDeliveryRepository(),
        ),
        "Customer summary delivery is not available",
    )
    asr_provider = _optional(
        lambda: create_asr_provider(settings), "ASR provider is not available"
    )
    language_provider = _optional(
        lambda: create_language_provider(settings), "Language provider is not available"
    )
    call_recording_store, transcript_reviser = _build_retranscription(
        settings, asr_provider, language_provider
    )

    # --- The call workflow ---
    runtime_improvement_service = build_runtime_improvement_service(
        active_improvement_repository
    )
    improvement_effectiveness_service = build_improvement_effectiveness_service(
        usage_repository=usage_repository,
        evidence_repository=evidence_repository,
    )
    # --- Recordings, telephony, and what each call's screen shows of them ---
    recording_archive = _build_recording_archive(settings, recording_repository)
    telephony_call_service = _build_telephony_call_service(
        settings, call_service, call_customer_service, live_state_store, call_routing
    )
    call_indicators = CallIndicators(
        live_state_store,
        # Kept as it is spoken: recordings are on and the call's audio is arriving.
        is_being_recorded=(
            None if recording_archive is None else telephony_call_service.stream_is_open
        ),
        has_recording=(
            None
            if recording_archive is None
            else lambda call_id: (
                (stored := recording_archive.get(call_id)) is not None and stored.is_available
            )
        ),
    )

    workflow_service = build_call_workflow_service(
        settings=settings,
        call_service=call_service,
        coverage_repository=coverage_repository,
        estimation_service=_build_estimation_service(settings, price_list_service),
        post_call_summary_service=build_post_call_summary_service(),
        customer_summary_delivery_service=customer_summary_delivery_service,
        customer_contact_resolver=customer_contact_resolver,
        learning_recorder=build_learning_call_recorder(
            evidence_repository=evidence_repository,
            observation_repository=observation_repository,
        ),
        post_call_summary_repository=post_call_summary_repository,
        runtime_improvement_service=runtime_improvement_service,
        improvement_usage_recorder=improvement_effectiveness_service,
        complaint_provider=complaint_provider,
        sentiment_provider=sentiment_provider,
        question_provider=question_provider,
        live_analyzer=_build_live_analyzer(
            settings, complaint_provider, sentiment_provider, escalation_provider
        ),
        category_descriptions=lambda: {
            c.name: c.description for c in complaint_category_catalog.custom()
        },
        escalation_service=escalation_service,
        complaint_lifecycle_service=complaint_lifecycle_service,
        customer_id_resolver=call_customer_service.resolve_customer_id,
        emerging_complaint_service=emerging_complaint_service,
        emerging_complaint_auto_discovery=settings.emerging_complaint_auto_discovery,
        live_state_store=live_state_store,
        live_analysis_ttl_seconds=settings.live_analysis_ttl_seconds,
        transcript_reviser=transcript_reviser,
        vehicle_model_resolver=call_customer_service.resolve_vehicle_model,
        alert_service=alert_service,
        # Accepted or skipped already: not suggested again.
        handled_questions=lambda call_id: tuple(
            outcome.question
            for outcome in question_outcome_repository.list_for_calls([call_id]).get(
                call_id, ()
            )
        ),
        indicators=call_indicators,
    )

    # --- The supervisor's view of the calls in progress ---
    # The same keys the workflow writes each call's live analysis under.
    live_analysis_store = LiveAnalysisStore(live_state_store, settings.live_analysis_ttl_seconds)
    live_calls = LiveCallsBoard(
        call_listing_query,
        coverage_repository,
        live_analysis_store,
        alert_service,
        cache_seconds=settings.live_calls_cache_seconds,
    )
    live_alert_sweeper = LiveAlertSweeper(
        call_listing_query,
        coverage_repository,
        alert_service,
        live_analysis_store,
        live_state_store,
        settings.live_alert_sweep_seconds,
    )

    # --- After the call, telephony and the background jobs ---
    post_call_repair_service = _build_post_call_repair_service(
        settings, call_service, workflow_service, post_call_summary_repository, live_state_store
    )
    background_jobs = _build_background_jobs(
        settings,
        call_service,
        workflow_service,
        telephony_call_service,
        post_call_repair_service,
        customer_summary_delivery_service,
        post_call_summary_repository,
        customer_contact_resolver,
        recording_archive,
        live_alert_sweeper,
    )
    telephony_provider = _optional(
        lambda: create_telephony_provider(settings), "Telephony provider is not available"
    )
    live_chunk_processing_service = _build_live_chunk_processing_service(
        settings,
        workflow_service,
        asr_provider,
        language_provider,
        live_state_store if shared_live_state else None,
    )

    services = ApiServices(
        call_service=call_service,
        call_listing=call_listing_query,
        live_calls=live_calls,
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
            pattern_rules=PatternRules(
                min_occurrences=settings.learning_pattern_min_corrections,
                min_calls=settings.learning_pattern_min_calls,
                min_correction_rate=settings.learning_pattern_min_correction_rate,
            ),
        ),
        auth=auth_service,
        login_throttle=LoginThrottle(
            live_state_store,
            LoginLimits(
                max_failures_per_email=settings.login_max_failures_per_email,
                max_failures_per_address=settings.login_max_failures_per_address,
                window_seconds=settings.login_failure_window_seconds,
            ),
        ),
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
        location_service=location_service,
        report_service=report_service,
        performance_service=performance_service,
        alert_service=alert_service,
        call_indicators=call_indicators,
        question_outcome_repository=question_outcome_repository,
        recording_archive=recording_archive,
        price_list_service=price_list_service,
        complaint_category_catalog=complaint_category_catalog,
        background_jobs=background_jobs,
        warm_up=(
            (lambda: _warm_up_live_models(settings))
            if live_chunk_processing_service is not None
            else None
        ),
        health_checks={"live_state": live_state_store.ping} if shared_live_state else {},
    )
    _register_gauges(services)
    return services


def _optional(build: Callable[[], _T], unavailable: str) -> _T | None:
    """build(), or None with a warning: a part that is not configured (or
    whose provider cannot be reached) is left out rather than stopping the
    rest of the app from starting."""
    try:
        return build()
    except Exception as exc:
        logger.warning("%s: %s", unavailable, exc)
        return None


def _built_or(fallback: Callable[[], _T], build: Callable[[], _T], falling_back: str) -> _T:
    """build(), or fallback() with a warning when it cannot be built."""
    try:
        return build()
    except Exception as exc:
        logger.warning("%s: %s", falling_back, exc)
        return fallback()


def _live_state(
    settings: Settings, live_state_store: LiveStateStore | None
) -> tuple[LiveStateStore, bool]:
    """The live state store, and whether API instances share it."""
    if live_state_store is not None:
        return live_state_store, True
    try:
        return (
            create_live_state_store(settings),
            settings.live_state_store_provider.strip().lower() != "in_memory",
        )
    except Exception as exc:
        if settings.is_production:
            raise
        logger.error("Live state store unavailable, keeping it in memory: %s", exc)
        return InMemoryLiveStateStore(), False


def _build_user_services(
    settings: Settings,
    user_repository: UserRepository,
    location_repository: LocationRepository,
) -> tuple[AuthService, UserManagementService]:
    auth_service = AuthService(user_repository)
    user_management_service = UserManagementService(
        user_repository,
        auth_service,
        locations=location_repository,
        default_country_code=settings.phone_default_country_code,
    )
    try:
        user_management_service.bootstrap_admin(
            settings.bootstrap_admin_email, settings.bootstrap_admin_password
        )
    except Exception:
        logger.exception("Could not bootstrap the first admin user")
    return auth_service, user_management_service


def _customer_directory(
    settings: Settings, customer_directory: CustomerDirectory | None
) -> CustomerDirectory:
    if customer_directory is not None:
        return customer_directory
    try:
        return create_customer_directory(settings)
    except Exception as exc:
        if settings.is_production:
            # Not something to find out from customers getting no
            # summary: a CRM that was asked for must load.
            raise
        logger.error("CRM is not available; customers will not be identified: %s", exc)
        return NoCustomerDirectory()


def _build_emerging_complaint_service(
    settings: Settings,
    repository: EmergingComplaintRepository,
    provider: EmergingComplaintDiscoveryProvider | None,
    call_service: CallService,
    coverage_repository: ConversationCoverageRepository,
    live_state_store: LiveStateStore,
    catalog: ComplaintCategoryCatalog,
) -> EmergingComplaintService:
    if provider is None:
        provider = _built_or(
            RuleBasedEmergingComplaintDiscoveryProvider,
            lambda: create_emerging_complaint_provider(settings=settings),
            "Falling back to rule-based emerging-complaint discovery",
        )
    return EmergingComplaintService(
        repository,
        provider,
        call_service,
        coverage_repository,
        max_calls=settings.emerging_complaint_discovery_max_calls,
        store=live_state_store,
        min_interval_seconds=settings.emerging_complaint_discovery_min_interval_seconds,
        catalog=catalog,
    )


def _build_retranscription(
    settings: Settings, asr_provider, language_provider
) -> tuple[CallRecordingStore | None, Callable | None]:
    """Post-call re-transcription from the call's recorded audio: where the
    recordings are kept, and what turns one into a better transcript. Both
    None when it is switched off or speech recognition is not configured."""
    if (
        not settings.post_call_retranscription_enabled
        or asr_provider is None
        or language_provider is None
    ):
        return None, None
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
    return call_recording_store, transcript_reviser


def _build_post_call_repair_service(
    settings: Settings,
    call_service: CallService,
    workflow_service: CallWorkflowService,
    post_call_summary_repository: PostCallSummaryRepository,
    live_state_store: LiveStateStore,
) -> PostCallRepairService:
    return PostCallRepairService(
        call_service,
        workflow_service.process_completed_call,
        post_call_summary_repository,
        live_state_store,
        min_age_seconds=settings.post_call_repair_min_age_seconds,
        max_attempts=settings.post_call_repair_max_attempts,
        scan_limit=settings.post_call_repair_scan_limit,
        background_interval_seconds=settings.post_call_repair_interval_seconds,
        rate_limit_wait=workflow_service.post_call_rate_limit_wait,
        rate_limit_retry_seconds=settings.post_call_repair_rate_limit_retry_seconds,
        rate_limit_give_up_seconds=settings.post_call_repair_rate_limit_give_up_seconds,
    )


def _build_recording_archive(
    settings: Settings, repository: "RecordingRepository | None"
) -> "RecordingArchive | None":
    """Where call recordings are kept; None when recording is off. A call
    is never recorded unencrypted: without a usable key nothing is kept
    (production refuses to start instead, see production_checks)."""
    if not settings.recording_enabled:
        return None
    try:
        from app.services.recording_archive import (
            InMemoryRecordingRepository,
            RecordingArchive,
            parse_key,
        )

        return RecordingArchive(
            repository or InMemoryRecordingRepository(),
            settings.recording_dir,
            parse_key(settings.recording_encryption_key),
            retention_days=settings.recording_retention_days,
        )
    except Exception as exc:
        if settings.is_production:
            raise
        logger.error("Call recordings will NOT be kept: %s", exc)
        return None


def _build_telephony_call_service(
    settings: Settings,
    call_service: CallService,
    call_customer_service: CallCustomerService,
    live_state_store: LiveStateStore,
    call_routing: CallRoutingService,
) -> TelephonyCallService:
    # Degrades to in-memory by itself, so an unconfigured store never
    # prevents the rest of the app (learning, auth, the manual /live
    # endpoint) from starting.
    return TelephonyCallService(
        call_service,
        _built_or(
            InMemoryTelephonyCallMappingRepository,
            lambda: create_call_mapping_repository(settings),
            "Falling back to in-memory call mapping store",
        ),
        call_customer_service=call_customer_service,
        live_state=live_state_store,
        call_routing=call_routing,
    )


def _build_background_jobs(
    settings: Settings,
    call_service: CallService,
    workflow_service: CallWorkflowService,
    telephony_call_service: TelephonyCallService,
    post_call_repair_service: PostCallRepairService,
    customer_summary_delivery_service: CustomerSummaryDeliveryService | None,
    post_call_summary_repository: PostCallSummaryRepository,
    customer_contact_resolver: Callable[[str], CustomerContact | None],
    recording_archive: "RecordingArchive | None" = None,
    live_alert_sweeper: LiveAlertSweeper | None = None,
) -> BackgroundJobRunner:
    """The periodic jobs; one with interval 0 is not run."""
    stale_call_sweeper = StaleCallSweeper(
        call_service,
        telephony_call_service.stream_is_open,
        workflow_service.complete_call,
        idle_seconds=settings.stale_call_idle_seconds,
        call_id_prefixes=(f"{settings.telephony_provider.strip().lower()}-",),
    )
    retries_summaries = (
        settings.customer_summary_enabled and customer_summary_delivery_service is not None
    )
    return BackgroundJobRunner(
        [
            PeriodicJob(
                "post_call_repair",
                settings.post_call_repair_interval_seconds,
                post_call_repair_service.run,
            ),
            PeriodicJob(
                "customer_summary_retry",
                settings.customer_summary_retry_interval_seconds if retries_summaries else 0.0,
                lambda: customer_summary_delivery_service.retry_unfinished(
                    post_call_summary_repository.get, customer_contact_resolver
                ),
            ),
            PeriodicJob(
                "stale_call_sweep",
                settings.stale_call_sweep_interval_seconds,
                stale_call_sweeper.run,
            ),
            PeriodicJob(
                "recording_retention",
                settings.recording_retention_sweep_seconds if recording_archive else 0.0,
                lambda: recording_archive.purge_expired(),
            ),
            PeriodicJob(
                "live_alert_sweep",
                settings.live_alert_sweep_seconds if live_alert_sweeper else 0.0,
                lambda: live_alert_sweeper.run(),
            ),
        ]
    )


def _build_live_chunk_processing_service(
    settings: Settings,
    workflow_service: CallWorkflowService,
    asr_provider,
    language_provider,
    shared_live_state_store: LiveStateStore | None,
):
    """Turns live audio into stored speech; None when speech recognition is
    not configured. shared_live_state_store: the store API instances share,
    when they do (it then holds the speaker sessions too)."""
    if asr_provider is None or language_provider is None:
        return None
    return _optional(
        lambda: build_live_chunk_processing_service(
            # Speech is stored and shown as soon as it is transcribed;
            # the AI analysis follows in the background (see
            # LiveAnalysisScheduler), so it never delays the next chunk.
            workflow_service=LiveAnalysisScheduler(
                workflow_service,
                min_interval_seconds=live_analysis_interval_seconds(settings),
                max_workers=max(1, settings.live_analysis_workers),
            ),
            diarization_segments=(),
            settings=settings,
            asr_provider=asr_provider,
            language_provider=language_provider,
            registry=build_speaker_session_registry(shared_live_state_store),
        ),
        "Live chunk processing is not available",
    )


def live_analysis_interval_seconds(settings: Settings) -> float:
    """How long a call's next live analysis waits after the previous one
    started: LIVE_ANALYSIS_MIN_INTERVAL_SECONDS, or none at all with
    LIVE_ANALYSIS_SPEED=fast."""
    speed = settings.live_analysis_speed.strip().lower()
    if speed == "fast":
        return 0.0
    if speed != "standard":
        logger.warning("Unknown LIVE_ANALYSIS_SPEED %r; using standard", speed)
    return settings.live_analysis_min_interval_seconds


def _warm_up_live_models(settings: Settings) -> None:
    try:
        warm_up_diarization(settings)
    except Exception as exc:
        logger.warning("Diarization model could not be preloaded: %s", exc)


def _register_gauges(services: ApiServices) -> None:
    """Gauges computed when /metrics is scraped."""
    _register_domain_gauges(
        services.call_service,
        services.escalation_service,
        services.complaint_lifecycle_service,
        services.post_call_repair_service,
    )
    background_jobs = services.background_jobs
    REGISTRY.register(
        Gauge(
            "background_job_overdue_intervals",
            "Time since each background job's last run ended, in its own intervals "
            "(about 1 when it runs on time; it keeps growing when the job hangs).",
            ("name",),
            lambda: {(name,): overdue for name, overdue in background_jobs.overdue_by().items()},
        )
    )
    REGISTRY.register(
        Gauge(
            "dependency_up",
            "1 when a dependency this instance needs answers (see /health/ready), else 0.",
            ("dependency",),
            lambda: _dependency_status(services.health_checks),
        )
    )


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


def _build_live_analyzer(
    settings: Settings,
    complaint_provider: ComplaintDetectionProvider,
    sentiment_provider: SentimentAnalysisProvider,
    escalation_provider: EscalationDetectionProvider,
) -> LLMLiveAnalysisProvider | None:
    """One combined LLM request during a call when LIVE_ANALYSIS_MODE is
    "combined" and the LLM providers it combines are in use."""
    mode = settings.live_analysis_mode.strip().lower()
    if mode == "separate":
        return None
    if mode != "combined":
        logger.warning("Unknown LIVE_ANALYSIS_MODE %r; using separate requests", mode)
        return None
    if not isinstance(complaint_provider, LLMComplaintProvider) or not isinstance(
        sentiment_provider, LLMSentimentProvider
    ):
        logger.warning(
            "LIVE_ANALYSIS_MODE=combined needs the LLM complaint and sentiment providers; "
            "using separate requests"
        )
        return None
    return LLMLiveAnalysisProvider(
        complaint_provider.llm_client,
        complaint_provider,
        sentiment_provider,
        escalation_provider.llm if isinstance(escalation_provider, HybridEscalationProvider) else None,
    )
