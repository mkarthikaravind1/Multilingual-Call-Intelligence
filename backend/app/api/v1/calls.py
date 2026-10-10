import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.api.dependencies import (
    get_question_outcome_repository,
    get_location_service,
    get_user_repository,
    get_call_customer_service,
    get_call_listing,
    get_call_service,
    get_optional_call_customer_service,
    get_workflow_service,
)
from app.api.v1.mappers import (
    to_analysis_response,
    to_call_list_response,
    to_call_response,
    to_call_stats_response,
    to_utterance,
)
from app.api.v1.schemas import (
    CallAlertResponse,
    CallAnalysisResponse,
    ComplaintCoverageResponse,
    LiveCallResponse,
    LiveCallsResponse,
    QuestionOutcomeRequest,
    QuestionOutcomeResponse,
    CallCustomerResponse,
    CallDirectoryEntry,
    CallDirectoryResponse,
    CallListResponse,
    CallSummaryDeliveriesResponse,
    CustomerSummaryDeliveryResponse,
    CallResponse,
    CallStatsResponse,
    CompleteCallRequest,
    IdentifyCustomerRequest,
    SelectVehicleRequest,
    StartCallRequest,
    UtteranceRequest,
)
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import CallDirection, ConversationStatus
from app.domain.user_repository import UserRepository
from app.services.location_service import LocationService
from app.services.call_customer_service import CallCustomerService
from app.services.call_listing import CallListFilters, CallListingQuery
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.api.security_dependencies import get_current_user, require_roles
from app.domain.call_alert import QuestionOutcome
from app.services.call_alerts import QuestionOutcomeRepository
from app.services.recording_archive import RecordingError, RecordingNotFoundError
from app.domain.user import User, UserRole


router = APIRouter(prefix="/calls", tags=["calls"])
# Separate path so it can never collide with a call_id of "stats".
stats_router = APIRouter(tags=["calls"])

DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100
# The live view shows this many active calls at most (the most recent).
MAX_LIVE_CALLS = 100
_SUPERVISORS = require_roles(UserRole.SUPERVISOR, UserRole.ADMIN)

@router.get("", response_model=CallListResponse)
def list_calls(
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
    status: list[ConversationStatus] = Query(
        default=[], description="Any of these statuses; none means all."
    ),
    high_escalation: bool = Query(
        False, description="Only calls escalated to high or critical (open or resolved)."
    ),
    customer: str | None = Query(
        None, max_length=100, description="Part of the customer name or vehicle registration."
    ),
    phone: str | None = Query(
        None, max_length=32, description="Digits that appear in the caller's number."
    ),
    # Epoch seconds; from inclusive, to exclusive.
    started_from: float | None = Query(None, ge=0),
    started_to: float | None = Query(None, ge=0),
    resolved_from: float | None = Query(None, ge=0),
    resolved_to: float | None = Query(None, ge=0),
    location_id: str | None = Query(None, max_length=64),
    executive_user_id: str | None = Query(None, max_length=64),
    direction: CallDirection | None = Query(None),
    listing: CallListingQuery = Depends(get_call_listing),
    _: User = Depends(get_current_user),
) -> CallListResponse:
    filters = CallListFilters(
        statuses=frozenset(status),
        high_escalation=high_escalation,
        customer=customer,
        phone=phone,
        started_from=started_from,
        started_to=started_to,
        resolved_from=resolved_from,
        resolved_to=resolved_to,
        location_id=location_id,
        executive_user_id=executive_user_id,
        direction=direction,
    )
    return to_call_list_response(listing.search(filters, limit, offset), limit, offset)

@stats_router.get("/call-directory", response_model=CallDirectoryResponse)
def get_call_directory(
    locations: LocationService = Depends(get_location_service),
    users: UserRepository = Depends(get_user_repository),
    _: User = Depends(get_current_user),
) -> CallDirectoryResponse:
    return CallDirectoryResponse(
        locations=[
            CallDirectoryEntry(id=l.location_id, name=l.name, is_active=l.is_active)
            for l in locations.list_locations()
        ],
        executives=sorted(
            (
                CallDirectoryEntry(id=u.user_id, name=u.name, is_active=u.is_active)
                for u in users.list_all()
            ),
            key=lambda entry: entry.name.casefold(),
        ),
    )


@stats_router.get("/live-calls", response_model=LiveCallsResponse)
def list_live_calls(
    listing: CallListingQuery = Depends(get_call_listing),
    workflow_service: CallWorkflowService = Depends(get_workflow_service),
    _: User = Depends(_SUPERVISORS),
) -> LiveCallsResponse:
    """Every active call with where it stands now. Reads only: the AI
    providers are never run from here."""
    page = listing.search(
        CallListFilters(statuses=frozenset({ConversationStatus.ACTIVE})), MAX_LIVE_CALLS, 0
    )
    items = []
    for call in page.items:
        try:
            # Some alerts become true just by time passing.
            workflow_service.refresh_alerts(call.call_id)
            analysis = workflow_service.analyze_call(call.call_id)
        except Exception:
            # e.g. the call completed and was cleared between the two reads.
            continue
        items.append(
            LiveCallResponse(
                call_id=call.call_id,
                start_time=call.start_time,
                direction=call.direction,
                location_name=call.location_name,
                executive_name=call.executive_name,
                caller_number=call.caller_number,
                customer_name=call.customer_name,
                utterance_count=call.utterance_count,
                sentiment=None if analysis.sentiment is None else analysis.sentiment.label,
                complaints=[
                    ComplaintCoverageResponse.model_validate(complaint)
                    for complaint in analysis.coverage.complaints
                    if complaint.status is not ComplaintCoverageStatus.NOT_RAISED
                ],
                escalation_level=call.escalation_level,
                escalation_status=call.escalation_status,
                alerts=[
                    CallAlertResponse.model_validate(alert)
                    for alert in analysis.alerts
                    if alert.is_open
                ],
            )
        )
    return LiveCallsResponse(items=items, total=page.total, now=time.time())


@stats_router.get("/call-stats", response_model=CallStatsResponse)
def get_call_stats(
    call_service: CallService = Depends(get_call_service),
    _: User = Depends(get_current_user),
) -> CallStatsResponse:
    return to_call_stats_response(call_service.count_calls_by_status())

@router.post("", response_model=CallResponse, status_code=status.HTTP_201_CREATED)
def start_call(
    payload: StartCallRequest,
    call_service: CallService = Depends(get_call_service),
    call_customer_service: CallCustomerService | None = Depends(
        get_optional_call_customer_service
    ),
    user: User = Depends(get_current_user),
) -> CallResponse:
    caller_number = None
    if payload.caller_number is not None:
        if call_customer_service is None:
            raise HTTPException(status_code=503, detail="Customer lookup is not configured.")
        # Validate before creating the call, so a bad number never leaves a call behind.
        caller_number = call_customer_service.normalize(payload.caller_number)
    start_time = time.time() if payload.start_time is None else payload.start_time
    # A call started here is taken by whoever is signed in, at their location.
    call = call_service.start_call(
        payload.call_id,
        start_time,
        direction=payload.direction,
        location_id=user.location_id,
        executive_user_id=user.user_id,
    )
    if call_customer_service is not None and caller_number is not None:
        call_customer_service.record_caller(call.call_id, caller_number)
    return to_call_response(call)

@router.get("/{call_id}", response_model=CallResponse)
def get_call(
    call_id: str,
    call_service: CallService = Depends(get_call_service),
    _: User = Depends(get_current_user),
) -> CallResponse:
    return to_call_response(call_service.get_call(call_id))

@router.post("/{call_id}/utterances", response_model=CallAnalysisResponse)
def add_utterance(
    call_id: str,
    payload: UtteranceRequest,
    workflow_service: CallWorkflowService = Depends(get_workflow_service),
    _: User = Depends(get_current_user),
) -> CallAnalysisResponse:
    result = workflow_service.process_utterance(call_id, to_utterance(payload))
    return to_analysis_response(call_id, result)

@router.get("/{call_id}/analysis", response_model=CallAnalysisResponse)
def get_analysis(
    call_id: str,
    workflow_service: CallWorkflowService = Depends(get_workflow_service),
    _: User = Depends(get_current_user),
) -> CallAnalysisResponse:
    return to_analysis_response(call_id, workflow_service.analyze_call(call_id))

@router.get("/{call_id}/customer", response_model=CallCustomerResponse)
def get_call_customer(
    call_id: str,
    call_service: CallService = Depends(get_call_service),
    call_customer_service: CallCustomerService = Depends(get_call_customer_service),
    _: User = Depends(get_current_user),
) -> CallCustomerResponse:
    call_service.get_call(call_id)  # 404 for an unknown call
    return CallCustomerResponse.model_validate(call_customer_service.get(call_id))


@router.put("/{call_id}/customer", response_model=CallCustomerResponse)
def identify_call_customer(
    call_id: str,
    payload: IdentifyCustomerRequest,
    call_service: CallService = Depends(get_call_service),
    call_customer_service: CallCustomerService = Depends(get_call_customer_service),
    user: User = Depends(get_current_user),
) -> CallCustomerResponse:
    call = call_service.get_call(call_id)
    # During the call its ICR identifies the caller. Afterwards the
    # summary has been sent and the complaints filed under that customer:
    # changing who the call was with is a correction for a supervisor.
    if call.status == ConversationStatus.COMPLETED and user.role not in (
        UserRole.SUPERVISOR,
        UserRole.ADMIN,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a supervisor can change the customer of a completed call.",
        )
    return CallCustomerResponse.model_validate(
        call_customer_service.identify(call_id, payload.phone_number, changed_by=user.user_id)
    )


@router.put("/{call_id}/customer/vehicle", response_model=CallCustomerResponse)
def select_call_vehicle(
    call_id: str,
    payload: SelectVehicleRequest,
    call_service: CallService = Depends(get_call_service),
    call_customer_service: CallCustomerService = Depends(get_call_customer_service),
    _: User = Depends(get_current_user),
) -> CallCustomerResponse:
    call_service.get_call(call_id)
    return CallCustomerResponse.model_validate(
        call_customer_service.select_vehicle(call_id, payload.vehicle_id)
    )


@router.get("/{call_id}/summary-delivery", response_model=CallSummaryDeliveriesResponse)
def get_summary_delivery(
    call_id: str,
    request: Request,
    call_service: CallService = Depends(get_call_service),
    _: User = Depends(get_current_user),
) -> CallSummaryDeliveriesResponse:
    call_service.get_call(call_id)  # 404 for an unknown call
    services = request.app.state.services
    delivery_service = services.customer_summary_delivery_service
    deliveries = () if delivery_service is None else delivery_service.list_for_call(call_id)
    return CallSummaryDeliveriesResponse(
        call_id=call_id,
        enabled=services.customer_summary_enabled and delivery_service is not None,
        deliveries=[
            CustomerSummaryDeliveryResponse.model_validate(delivery) for delivery in deliveries
        ],
    )


@router.post("/{call_id}/complete", response_model=CallResponse)
def complete_call(
    call_id: str,
    payload: CompleteCallRequest,
    workflow_service: CallWorkflowService = Depends(get_workflow_service),
    _: User = Depends(get_current_user),
) -> CallResponse:
    end_time = time.time() if payload.end_time is None else payload.end_time
    completion = workflow_service.complete_call(call_id, end_time)
    return to_call_response(completion.conversation)

@router.get("/{call_id}/question-outcomes", response_model=list[QuestionOutcomeResponse])
def list_question_outcomes(
    call_id: str,
    call_service: CallService = Depends(get_call_service),
    outcomes: QuestionOutcomeRepository = Depends(get_question_outcome_repository),
    _: User = Depends(get_current_user),
) -> list[QuestionOutcomeResponse]:
    call_service.get_call(call_id)  # 404 for an unknown call
    return [
        QuestionOutcomeResponse.model_validate(outcome)
        for outcome in outcomes.list_for_calls([call_id]).get(call_id, ())
    ]


@router.post("/{call_id}/question-outcomes", response_model=QuestionOutcomeResponse)
def record_question_outcome(
    call_id: str,
    payload: QuestionOutcomeRequest,
    call_service: CallService = Depends(get_call_service),
    outcomes: QuestionOutcomeRepository = Depends(get_question_outcome_repository),
    user: User = Depends(get_current_user),
) -> QuestionOutcomeResponse:
    """The executive accepted (will ask) or skipped a suggested question.
    Choosing again for the same question replaces the earlier choice."""
    call_service.get_call(call_id)  # 404 for an unknown call
    outcome = QuestionOutcome(
        call_id=call_id,
        question=payload.question.strip(),
        target_category=payload.target_category.strip(),
        outcome=payload.outcome,
        user_id=user.user_id,
        created_at=time.time(),
    )
    outcomes.save(outcome)
    return QuestionOutcomeResponse.model_validate(outcome)


class CallRecordingResponse(BaseModel):
    # Whether this server keeps call recordings at all.
    enabled: bool
    # Whether this call has one that can be listened to now.
    available: bool
    duration_seconds: float | None = None
    size_bytes: int | None = None
    # 2: the caller on the left, the other party on the right.
    channels: int | None = None
    created_at: float | None = None
    # When the recording is (or was) due to be removed.
    delete_after: float | None = None
    deleted_at: float | None = None
    # How many times it has been listened to.
    plays: int = 0


@router.get("/{call_id}/recording", response_model=CallRecordingResponse)
def get_call_recording(
    call_id: str,
    request: Request,
    call_service: CallService = Depends(get_call_service),
    _: User = Depends(_SUPERVISORS),
) -> CallRecordingResponse:
    call_service.get_call(call_id)  # 404 for an unknown call
    archive = request.app.state.services.recording_archive
    stored = None if archive is None else archive.get(call_id)
    if stored is None:
        return CallRecordingResponse(enabled=archive is not None, available=False)
    return CallRecordingResponse(
        enabled=True,
        available=stored.is_available,
        duration_seconds=stored.duration_seconds,
        size_bytes=stored.size_bytes,
        channels=stored.channels,
        created_at=stored.created_at,
        delete_after=stored.delete_after,
        deleted_at=stored.deleted_at,
        plays=len(archive.plays(call_id)),
    )


@router.get("/{call_id}/recording/audio")
async def get_call_recording_audio(
    call_id: str,
    request: Request,
    call_service: CallService = Depends(get_call_service),
    user: User = Depends(_SUPERVISORS),
) -> Response:
    """The call's recording, decrypted, as a WAV file. Every request is
    logged against the user as a listen."""
    await run_in_threadpool(call_service.get_call, call_id)  # 404 for an unknown call
    archive = request.app.state.services.recording_archive
    if archive is None:
        raise HTTPException(status_code=404, detail="Call recordings are not kept on this server.")
    try:
        wav = await run_in_threadpool(archive.read, call_id, user.user_id)
    except RecordingNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RecordingError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(
        wav,
        media_type="audio/wav",
        # Never cached: a copy outside the server would outlive the retention period.
        headers={"Cache-Control": "no-store"},
    )
