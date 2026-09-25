from fastapi import APIRouter, Depends

from app.api.dependencies import get_learning_service
from app.api.v1.learning_schemas import (
    LearningCandidateResponse,
    LearningEvidenceResponse,
    LearningPatternResponse,
)
from app.services.learning_management_service import LearningManagementService
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
    _: User = Depends(get_current_user),
) -> list[LearningEvidenceResponse]:
    return [LearningEvidenceResponse.model_validate(e) for e in service.list_evidence()]