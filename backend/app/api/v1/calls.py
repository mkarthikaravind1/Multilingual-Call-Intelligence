from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.dependencies import (
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
    CallAnalysisResponse,
    CallCustomerResponse,
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
from app.domain.conversation import ConversationStatus
from app.services.call_customer_service import CallCustomerService
from app.services.call_listing import CallListFilters, CallListingQuery
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.api.security_dependencies import get_current_user
from app.domain.user import User, UserRole


router = APIRouter(prefix="/calls", tags=["calls"])
# Separate path so it can never collide with a call_id of "stats".
stats_router = APIRouter(tags=["calls"])

DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100

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
    )
    return to_call_list_response(listing.search(filters, limit, offset), limit, offset)

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
    _: User = Depends(get_current_user),
) -> CallResponse:
    caller_number = None
    if payload.caller_number is not None:
        if call_customer_service is None:
            raise HTTPException(status_code=503, detail="Customer lookup is not configured.")
        # Validate before creating the call, so a bad number never leaves a call behind.
        caller_number = call_customer_service.normalize(payload.caller_number)
    call = call_service.start_call(payload.call_id, payload.start_time)
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
    completion = workflow_service.complete_call(call_id, payload.end_time)
    return to_call_response(completion.conversation)