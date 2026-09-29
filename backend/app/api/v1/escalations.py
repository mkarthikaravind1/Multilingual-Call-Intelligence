from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_escalation_service
from app.api.security_dependencies import require_roles
from app.api.v1.mappers import to_escalation_response
from app.api.v1.schemas import EscalationResponse, ResolveEscalationRequest
from app.domain.user import User, UserRole
from app.services.escalation_service import EscalationService

router = APIRouter(prefix="/escalations", tags=["escalations"])

_SUPERVISORS = require_roles(UserRole.SUPERVISOR, UserRole.ADMIN)


@router.get("", response_model=list[EscalationResponse])
def list_escalations(
    state: Literal["active", "resolved"] = Query("active"),
    service: EscalationService = Depends(get_escalation_service),
    _: User = Depends(_SUPERVISORS),
) -> list[EscalationResponse]:
    """Active escalations most severe first; resolved ones newest first."""
    return [
        to_escalation_response(escalation)
        for escalation in service.list_queue(active=state == "active")
    ]


@router.post("/{call_id}/acknowledge", response_model=EscalationResponse)
def acknowledge_escalation(
    call_id: str,
    service: EscalationService = Depends(get_escalation_service),
    user: User = Depends(_SUPERVISORS),
) -> EscalationResponse:
    return to_escalation_response(service.acknowledge(call_id, user.email))


@router.post("/{call_id}/resolve", response_model=EscalationResponse)
def resolve_escalation(
    call_id: str,
    payload: ResolveEscalationRequest,
    service: EscalationService = Depends(get_escalation_service),
    user: User = Depends(_SUPERVISORS),
) -> EscalationResponse:
    return to_escalation_response(service.resolve(call_id, user.email, payload.note))
