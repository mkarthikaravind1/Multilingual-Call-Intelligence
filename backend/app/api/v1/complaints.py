from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import (
    get_call_service,
    get_complaint_lifecycle_service,
    get_emerging_complaint_service,
    get_optional_call_customer_service,
)
from app.api.security_dependencies import get_current_user, require_roles
from app.api.v1.complaint_schemas import (
    CallComplaintsResponse,
    ComplaintActionRequest,
    ComplaintResponse,
    DiscoveryRunResponse,
    EmergingComplaintResponse,
    EmergingComplaintsResponse,
    ReviewEmergingComplaintRequest,
    to_complaint_response,
    to_discovery_run_response,
    to_emerging_complaint_response,
)
from app.domain.complaint_lifecycle import ComplaintLifecycleStatus
from app.domain.emerging_complaint_candidate import EmergingComplaintReviewStatus
from app.domain.user import User, UserRole
from app.services.call_customer_service import CallCustomerService
from app.services.call_service import CallService
from app.services.complaint_lifecycle_service import ComplaintLifecycleService
from app.services.emerging_complaint_service import EmergingComplaintService

router = APIRouter(prefix="/complaints", tags=["complaints"])
call_complaints_router = APIRouter(tags=["complaints"])
emerging_router = APIRouter(prefix="/emerging-complaints", tags=["emerging complaints"])

_SUPERVISORS = require_roles(UserRole.SUPERVISOR, UserRole.ADMIN)


@router.get("", response_model=list[ComplaintResponse])
def list_complaints(
    state: Literal["open", "resolved", "all"] = Query("open"),
    limit: int = Query(200, ge=1, le=500),
    service: ComplaintLifecycleService = Depends(get_complaint_lifecycle_service),
    _: User = Depends(get_current_user),
) -> list[ComplaintResponse]:
    """Open complaints: follow-ups first, then the oldest first."""
    return [to_complaint_response(view) for view in service.list_queue(state, limit)]


@router.get("/{complaint_id}", response_model=ComplaintResponse)
def get_complaint(
    complaint_id: str,
    service: ComplaintLifecycleService = Depends(get_complaint_lifecycle_service),
    _: User = Depends(get_current_user),
) -> ComplaintResponse:
    return to_complaint_response(service.get_view(complaint_id))


@router.post("/{complaint_id}/status", response_model=ComplaintResponse)
def update_complaint_status(
    complaint_id: str,
    payload: ComplaintActionRequest,
    service: ComplaintLifecycleService = Depends(get_complaint_lifecycle_service),
    user: User = Depends(get_current_user),
) -> ComplaintResponse:
    return to_complaint_response(
        service.apply_action(
            complaint_id, ComplaintLifecycleStatus(payload.status), user.email, payload.note
        )
    )


@call_complaints_router.get("/calls/{call_id}/complaints", response_model=CallComplaintsResponse)
def get_call_complaints(
    call_id: str,
    call_service: CallService = Depends(get_call_service),
    service: ComplaintLifecycleService = Depends(get_complaint_lifecycle_service),
    call_customer_service: CallCustomerService | None = Depends(
        get_optional_call_customer_service
    ),
    _: User = Depends(get_current_user),
) -> CallComplaintsResponse:
    """The call's complaints plus the customer's complaints from other calls."""
    call_service.get_call(call_id)  # 404 for an unknown call
    customer_id = (
        call_customer_service.resolve_customer_id(call_id)
        if call_customer_service is not None
        else None
    )
    if customer_id is not None:
        # The customer may have been identified after the call ended.
        service.attach_customer(call_id, customer_id)
    return CallComplaintsResponse(
        call_id=call_id,
        customer_id=customer_id,
        complaints=[to_complaint_response(view) for view in service.list_for_call(call_id)],
        customer_history=(
            [
                to_complaint_response(view)
                for view in service.customer_history(customer_id, exclude_call_id=call_id)
            ]
            if customer_id is not None
            else []
        ),
    )


@emerging_router.get("", response_model=EmergingComplaintsResponse)
def list_emerging_complaints(
    status: EmergingComplaintReviewStatus | None = Query(None),
    service: EmergingComplaintService = Depends(get_emerging_complaint_service),
    _: User = Depends(get_current_user),
) -> EmergingComplaintsResponse:
    return EmergingComplaintsResponse(
        candidates=[
            to_emerging_complaint_response(candidate)
            for candidate in service.list_candidates(status)
        ],
        last_run=to_discovery_run_response(service.last_run),
    )


@emerging_router.post("/discover", response_model=DiscoveryRunResponse)
def run_emerging_complaint_discovery(
    service: EmergingComplaintService = Depends(get_emerging_complaint_service),
    _: User = Depends(_SUPERVISORS),
) -> DiscoveryRunResponse:
    return to_discovery_run_response(service.discover())


@emerging_router.post("/{candidate_id}/review", response_model=EmergingComplaintResponse)
def review_emerging_complaint(
    candidate_id: str,
    payload: ReviewEmergingComplaintRequest,
    service: EmergingComplaintService = Depends(get_emerging_complaint_service),
    user: User = Depends(_SUPERVISORS),
) -> EmergingComplaintResponse:
    return to_emerging_complaint_response(
        service.review(candidate_id, payload.decision, user.email, payload.note)
    )
