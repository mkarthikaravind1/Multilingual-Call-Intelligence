from collections.abc import Callable
from typing import TYPE_CHECKING
from dataclasses import dataclass, field

from fastapi import HTTPException, Request
from starlette.requests import HTTPConnection

from app.ai.asr.provider import ASRProvider
from app.api.v1.live_handler import LiveCallHandler
from app.domain.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.login_throttle import LoginThrottle
from app.services.call_alerts import CallAlertService, QuestionOutcomeRepository
from app.services.call_indicators import CallIndicators
from app.services.call_customer_service import CallCustomerService
from app.services.call_recording_store import CallRecordingStore
from app.services.call_listing import CallListingQuery
from app.services.complaint_category_catalog import ComplaintCategoryCatalog
from app.services.complaint_lifecycle_service import ComplaintLifecycleService
from app.services.emerging_complaint_service import EmergingComplaintService
from app.services.escalation_service import EscalationService
from app.services.background_jobs import BackgroundJobRunner
from app.services.live_calls import LiveCallsBoard
from app.services.live_state_store import LiveStateStore
from app.services.location_service import LocationService
from app.services.post_call_repair_service import PostCallRepairService
from app.services.price_list_service import PriceListService
from app.services.performance import PerformanceService
from app.services.reporting import ReportService
from app.services.user_management_service import UserManagementService
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.services.customer_summary_delivery_service import CustomerSummaryDeliveryService
from app.services.learning_management_service import LearningManagementService
from app.services.live_chunk_processing_service import LiveChunkProcessingService
from app.services.telephony_call_service import TelephonyCallService
from app.telephony.provider import TelephonyProvider
from starlette.requests import HTTPConnection

if TYPE_CHECKING:
    from app.services.recording_archive import RecordingArchive


@dataclass(frozen=True)
class ApiServices:
    call_service: CallService
    workflow_service: CallWorkflowService
    call_listing: CallListingQuery | None = None
    # The supervisor's view of every call in progress.
    live_calls: LiveCallsBoard | None = None

    learning: LearningManagementService | None = None
    auth: AuthService | None = None
    # Limits password guessing; None: no limit (e.g. some tests).
    login_throttle: LoginThrottle | None = None
    user_repository: UserRepository | None = None

    telephony_provider: TelephonyProvider | None = None
    telephony_call_service: TelephonyCallService | None = None
    live_chunk_processing_service: LiveChunkProcessingService | None = None
    customer_summary_delivery_service: CustomerSummaryDeliveryService | None = None
    asr_provider: ASRProvider | None = None
    telephony_stream_flush_seconds: float = 4.0
    # Live call audio kept for post-call re-transcription (None: not kept).
    call_recording_store: CallRecordingStore | None = None
    call_customer_service: CallCustomerService | None = None
    customer_summary_enabled: bool = False
    escalation_service: EscalationService | None = None
    complaint_lifecycle_service: ComplaintLifecycleService | None = None
    emerging_complaint_service: EmergingComplaintService | None = None
    # Built-in complaint categories plus accepted emerging themes.
    complaint_category_catalog: ComplaintCategoryCatalog | None = None
    live_state_store: LiveStateStore | None = None
    # How often an open live-call WebSocket checks for new analysis to push.
    live_call_push_interval_seconds: float = 0.5
    post_call_repair_service: PostCallRepairService | None = None
    user_management_service: UserManagementService | None = None
    location_service: LocationService | None = None
    report_service: ReportService | None = None
    performance_service: PerformanceService | None = None
    alert_service: CallAlertService | None = None
    # What the AI is doing on each call, and where its record stands.
    call_indicators: CallIndicators | None = None
    question_outcome_repository: QuestionOutcomeRepository | None = None
    # Encrypted call recordings on disk; None when recording is off.
    recording_archive: "RecordingArchive | None" = None
    price_list_service: PriceListService | None = None
    background_jobs: BackgroundJobRunner | None = None
    # Loads slow models (e.g. diarization) in the background at startup.
    warm_up: Callable[[], None] | None = None
    # name -> callable raising when that dependency is unavailable.
    health_checks: dict[str, Callable[[], object]] = field(default_factory=dict)


def get_post_call_repair_service(connection: HTTPConnection) -> PostCallRepairService:
    service = connection.app.state.services.post_call_repair_service
    if service is None:
        raise HTTPException(status_code=503, detail="Post-call repair is not configured.")
    return service


def get_user_management_service(connection: HTTPConnection) -> UserManagementService:
    service = connection.app.state.services.user_management_service
    if service is None:
        raise HTTPException(status_code=503, detail="User management is not configured.")
    return service


def get_location_service(connection: HTTPConnection) -> LocationService:
    service = connection.app.state.services.location_service
    if service is None:
        raise HTTPException(status_code=503, detail="Locations are not configured.")
    return service


def get_report_service(connection: HTTPConnection) -> ReportService:
    service = connection.app.state.services.report_service
    if service is None:
        raise HTTPException(status_code=503, detail="Reports are not configured.")
    return service


def get_performance_service(connection: HTTPConnection) -> PerformanceService:
    service = connection.app.state.services.performance_service
    if service is None:
        raise HTTPException(status_code=503, detail="Reports are not configured.")
    return service


def get_alert_service(connection: HTTPConnection) -> CallAlertService | None:
    return connection.app.state.services.alert_service


def get_question_outcome_repository(connection: HTTPConnection) -> QuestionOutcomeRepository:
    repository = connection.app.state.services.question_outcome_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="Question outcomes are not configured.")
    return repository


def get_price_list_service(connection: HTTPConnection) -> PriceListService:
    service = connection.app.state.services.price_list_service
    if service is None:
        raise HTTPException(status_code=503, detail="The price list is not configured.")
    return service


def get_complaint_lifecycle_service(connection: HTTPConnection) -> ComplaintLifecycleService:
    service = connection.app.state.services.complaint_lifecycle_service
    if service is None:
        raise HTTPException(status_code=503, detail="Complaint tracking is not configured.")
    return service


def get_complaint_category_catalog(connection: HTTPConnection) -> ComplaintCategoryCatalog:
    catalog = connection.app.state.services.complaint_category_catalog
    if catalog is None:
        from app.services.complaint_category_catalog import BUILT_IN_CATALOG

        return BUILT_IN_CATALOG
    return catalog


def get_emerging_complaint_service(connection: HTTPConnection) -> EmergingComplaintService:
    service = connection.app.state.services.emerging_complaint_service
    if service is None:
        raise HTTPException(
            status_code=503, detail="Emerging-complaint discovery is not configured."
        )
    return service


def get_escalation_service(connection: HTTPConnection) -> EscalationService:
    service = connection.app.state.services.escalation_service
    if service is None:
        raise HTTPException(status_code=503, detail="Escalations are not configured.")
    return service


def get_optional_escalation_service(connection: HTTPConnection) -> EscalationService | None:
    return connection.app.state.services.escalation_service


def get_optional_call_customer_service(
    connection: HTTPConnection,
) -> CallCustomerService | None:
    return connection.app.state.services.call_customer_service


def get_call_customer_service(connection: HTTPConnection) -> CallCustomerService:
    service = connection.app.state.services.call_customer_service
    if service is None:
        raise HTTPException(status_code=503, detail="Customer lookup is not configured.")
    return service


def get_telephony_stream_flush_seconds(connection: HTTPConnection) -> float:
    return connection.app.state.services.telephony_stream_flush_seconds


def get_call_recording_store(connection: HTTPConnection) -> CallRecordingStore | None:
    return connection.app.state.services.call_recording_store

def get_learning_service(request: Request) -> LearningManagementService:
    return request.app.state.services.learning


def get_live_call_handler(connection: HTTPConnection) -> LiveCallHandler:
    services = connection.app.state.services
    return LiveCallHandler(
        services.call_service,
        services.workflow_service,
    )


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.services.auth


def get_login_throttle(request: Request) -> LoginThrottle | None:
    return request.app.state.services.login_throttle


def get_user_repository(request: Request) -> UserRepository:
    return request.app.state.services.user_repository

def get_telephony_call_service(
    connection: HTTPConnection,
) -> TelephonyCallService:
    return connection.app.state.services.telephony_call_service

def get_telephony_provider(connection: HTTPConnection) -> TelephonyProvider | None:
    return connection.app.state.services.telephony_provider

def get_asr_provider(connection: HTTPConnection) -> ASRProvider | None:
    return connection.app.state.services.asr_provider


def get_live_chunk_processing_service(
    connection: HTTPConnection,
) -> LiveChunkProcessingService | None:
    return connection.app.state.services.live_chunk_processing_service


def get_call_listing(connection: HTTPConnection) -> CallListingQuery:
    listing = connection.app.state.services.call_listing
    if listing is None:
        raise HTTPException(status_code=503, detail="The call list is not configured.")
    return listing


def get_live_calls(connection: HTTPConnection) -> LiveCallsBoard:
    board = connection.app.state.services.live_calls
    if board is None:
        raise HTTPException(status_code=503, detail="The live view is not configured.")
    return board


def get_call_service(connection: HTTPConnection) -> CallService:
    return connection.app.state.services.call_service


def get_workflow_service(connection: HTTPConnection) -> CallWorkflowService:
    return connection.app.state.services.workflow_service