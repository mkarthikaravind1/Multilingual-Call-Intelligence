from fastapi import APIRouter, Depends, status

from app.api.dependencies import (
    get_call_service,
    get_learning_service,
    get_optional_call_customer_service,
)
from app.api.v1.learning_schemas import (
    ActiveImprovementResponse,
    CallObservationResponse,
    LearningCandidateResponse,
    LearningEvidenceResponse,
    LearningFeedbackRequest,
    LearningFeedbackResponse,
    LearningPatternResponse,
)
from app.domain.learning_feedback import FeedbackSource
from app.services.call_customer_service import CallCustomerService
from app.services.call_service import CallService
from app.services.learning_management_service import (
    CallObservation,
    ImprovementOverview,
    LearningManagementService,
)
from app.api.security_dependencies import get_current_user, require_roles
from app.domain.user import User, UserRole

router = APIRouter(prefix="/learning", tags=["learning"])

@router.get("/candidates", response_model=list[LearningCandidateResponse])
def list_candidates(
    service: LearningManagementService = Depends(get_learning_service),
    _: User = Depends(get_current_user),
) -> list[LearningCandidateResponse]:
    return [LearningCandidateResponse.model_validate(c) for c in service.list_candidates()]


@router.get("/candidates/{candidate_id}", response_model=LearningCandidateResponse)
def get_candidate(
    candidate_id: str,
    service: LearningManagementService = Depends(get_learning_service),
    _: User = Depends(get_current_user),
) -> LearningCandidateResponse:
    return LearningCandidateResponse.model_validate(service.get_candidate(candidate_id))


@router.post("/candidates/{candidate_id}/approve", response_model=LearningCandidateResponse)
def approve_candidate(
    candidate_id: str,
    service: LearningManagementService = Depends(get_learning_service),
    _: User = Depends(require_roles(UserRole.SUPERVISOR, UserRole.ADMIN)),
) -> LearningCandidateResponse:
    return LearningCandidateResponse.model_validate(service.approve(candidate_id))


@router.post("/candidates/{candidate_id}/reject", response_model=LearningCandidateResponse)
def reject_candidate(
    candidate_id: str,
    service: LearningManagementService = Depends(get_learning_service),
    _: User = Depends(require_roles(UserRole.SUPERVISOR, UserRole.ADMIN)),
) -> LearningCandidateResponse:
    return LearningCandidateResponse.model_validate(service.reject(candidate_id))


@router.get("/patterns", response_model=list[LearningPatternResponse])
def list_patterns(
    service: LearningManagementService = Depends(get_learning_service),
    _: User = Depends(get_current_user),
) -> list[LearningPatternResponse]:
    return [LearningPatternResponse.model_validate(p) for p in service.list_patterns()]


@router.get("/evidence", response_model=list[LearningEvidenceResponse])
def list_evidence(
    service: LearningManagementService = Depends(get_learning_service),
    call_customer_service: CallCustomerService | None = Depends(
        get_optional_call_customer_service
    ),
    _: User = Depends(get_current_user),
) -> list[LearningEvidenceResponse]:
    """Each record carries its call's stored customer name and vehicle."""
    evidence = service.list_evidence()
    links = (
        call_customer_service.stored_links({e.call_id for e in evidence})
        if call_customer_service is not None
        else {}
    )
    responses = []
    for item in evidence:
        link = links.get(item.call_id)
        responses.append(
            LearningEvidenceResponse.model_validate(item).model_copy(
                update={
                    "customer_name": None if link is None else link.customer_name,
                    "vehicle_registration": None if link is None else link.vehicle_registration,
                }
            )
        )
    return responses


# --- Human feedback on a call's AI output ---

@router.get(
    "/calls/{call_id}/observations", response_model=list[CallObservationResponse]
)
def list_call_observations(
    call_id: str,
    service: LearningManagementService = Depends(get_learning_service),
    call_service: CallService = Depends(get_call_service),
    _: User = Depends(get_current_user),
) -> list[CallObservationResponse]:
    call_service.get_call(call_id)  # 404 for an unknown call
    return [_to_observation_response(item) for item in service.list_call_observations(call_id)]


@router.post(
    "/calls/{call_id}/feedback",
    response_model=LearningFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_feedback(
    call_id: str,
    payload: LearningFeedbackRequest,
    service: LearningManagementService = Depends(get_learning_service),
    call_service: CallService = Depends(get_call_service),
    user: User = Depends(get_current_user),
) -> LearningFeedbackResponse:
    call_service.get_call(call_id)  # 404 for an unknown call
    feedback = service.submit_feedback(
        call_id=call_id,
        observation_id=payload.observation_id,
        feedback_type=payload.feedback_type,
        corrected_value=payload.corrected_value,
        outcome=payload.outcome,
        notes=payload.notes,
        source=(
            FeedbackSource.ICR if user.role is UserRole.ICR else FeedbackSource.SUPERVISOR
        ),
    )
    return LearningFeedbackResponse.model_validate(feedback)


# --- Active improvements ---

@router.get("/improvements", response_model=list[ActiveImprovementResponse])
def list_improvements(
    service: LearningManagementService = Depends(get_learning_service),
    _: User = Depends(get_current_user),
) -> list[ActiveImprovementResponse]:
    return [_to_improvement_response(item) for item in service.list_improvements()]


@router.post(
    "/improvements/{improvement_id}/deactivate",
    response_model=ActiveImprovementResponse,
)
def deactivate_improvement(
    improvement_id: str,
    service: LearningManagementService = Depends(get_learning_service),
    _: User = Depends(require_roles(UserRole.SUPERVISOR, UserRole.ADMIN)),
) -> ActiveImprovementResponse:
    return _to_improvement_response(service.deactivate_improvement(improvement_id))


def _to_observation_response(item: CallObservation) -> CallObservationResponse:
    observation = item.observation
    return CallObservationResponse(
        observation_id=observation.observation_id,
        call_id=observation.call_id,
        component=observation.component,
        predicted_value=observation.predicted_value,
        entity_id=observation.entity_id,
        confidence=observation.confidence,
        created_at=observation.created_at,
        correction_options=list(item.correction_options),
        feedback=(
            None
            if item.feedback is None
            else LearningFeedbackResponse.model_validate(item.feedback)
        ),
    )


def _to_improvement_response(item: ImprovementOverview) -> ActiveImprovementResponse:
    improvement = item.improvement
    return ActiveImprovementResponse(
        improvement_id=improvement.improvement_id,
        candidate_id=improvement.candidate_id,
        component=improvement.component,
        guidance=improvement.specification.current_behavior,
        proposed_behavior=improvement.specification.proposed_behavior,
        status=improvement.status,
        activated_at=improvement.activated_at,
        deactivated_at=improvement.deactivated_at,
        usage_count=item.effectiveness.usage_count,
        feedback_count=item.effectiveness.evidence_count,
        effectiveness_status=item.effectiveness.status,
    )