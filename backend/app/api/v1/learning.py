from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

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
from app.ai.learning_guidance import guidance_text
from app.domain.improvement_effectiveness import ImprovementEffect, ImprovementEffectMeasure
from app.domain.learning_feedback import FeedbackSource
from app.services.call_customer_service import CallCustomerService
from app.services.call_service import CallService
from app.services.conversation_service import ConversationNotFoundError
from app.services.training_export import TrainingExport, export_training_data
from app.services.learning_management_service import (
    CallObservation,
    ImprovementOverview,
    LearningManagementService,
)
from app.api.security_dependencies import get_current_user, require_roles
from app.domain.user import User, UserRole

router = APIRouter(prefix="/learning", tags=["learning"])

_ADMINS = require_roles(UserRole.ADMIN)
_SUPERVISORS = require_roles(UserRole.SUPERVISOR)

# The evidence list grows by several records per call.
EVIDENCE_PAGE_SIZE = 500
MAX_EVIDENCE_PAGE_SIZE = 2000

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
    _: User = Depends(_SUPERVISORS),
) -> LearningCandidateResponse:
    return LearningCandidateResponse.model_validate(service.approve(candidate_id))


@router.post("/candidates/{candidate_id}/reject", response_model=LearningCandidateResponse)
def reject_candidate(
    candidate_id: str,
    service: LearningManagementService = Depends(get_learning_service),
    _: User = Depends(_SUPERVISORS),
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
    response: Response,
    limit: int = Query(EVIDENCE_PAGE_SIZE, ge=1, le=MAX_EVIDENCE_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    service: LearningManagementService = Depends(get_learning_service),
    call_customer_service: CallCustomerService | None = Depends(
        get_optional_call_customer_service
    ),
    _: User = Depends(get_current_user),
) -> list[LearningEvidenceResponse]:
    """Newest first, a page at a time; the X-Total-Count header has the
    number of records in all. Each record carries its call's stored
    customer name and vehicle."""
    evidence = service.list_evidence(limit, offset)
    response.headers["X-Total-Count"] = str(service.count_evidence())
    return _evidence_responses(evidence, call_customer_service)


def _evidence_responses(
    evidence, call_customer_service: CallCustomerService | None
) -> list[LearningEvidenceResponse]:
    """Each record with its call's stored customer name and vehicle."""
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


class CorrectionsResponse(BaseModel):
    # What people corrected or rated, newest first.
    corrections: list[LearningEvidenceResponse]
    # Every record there is, the AI's own outputs included.
    evidence_total: int


@router.get("/corrections", response_model=CorrectionsResponse)
def list_corrections(
    service: LearningManagementService = Depends(get_learning_service),
    call_customer_service: CallCustomerService | None = Depends(
        get_optional_call_customer_service
    ),
    _: User = Depends(get_current_user),
) -> CorrectionsResponse:
    """The part of the evidence a person reads: where someone corrected
    the AI or rated what it suggested. The rest (one record per AI output)
    is counted, not listed."""
    return CorrectionsResponse(
        corrections=_evidence_responses(service.list_corrections(), call_customer_service),
        evidence_total=service.count_evidence(),
    )


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
        created_by=user.user_id,
    )
    return LearningFeedbackResponse.model_validate(feedback)


# --- Active improvements ---

class TrainingDataResponse(BaseModel):
    # AI outputs a person has judged.
    examples: int
    # Of those, with a correct answer and a transcript: usable to fine-tune.
    with_messages: int
    by_task: dict[str, int]


def _training_export(
    service: LearningManagementService, call_service: CallService
) -> TrainingExport:
    def get_call(call_id: str):
        try:
            return call_service.get_call(call_id)
        except ConversationNotFoundError:
            return None

    return export_training_data(service.list_reviewed(), get_call)


@router.get("/training-data", response_model=TrainingDataResponse)
async def training_data(
    service: LearningManagementService = Depends(get_learning_service),
    call_service: CallService = Depends(get_call_service),
    _: User = Depends(_ADMINS),
) -> TrainingDataResponse:
    """How much reviewed AI output there is to train a model on."""
    export = await run_in_threadpool(_training_export, service, call_service)
    return TrainingDataResponse(
        examples=export.examples, with_messages=export.with_messages, by_task=export.by_task
    )


@router.get("/training-data/export")
async def export_training_file(
    service: LearningManagementService = Depends(get_learning_service),
    call_service: CallService = Depends(get_call_service),
    _: User = Depends(_ADMINS),
) -> Response:
    """Every reviewed AI output with its transcript, as JSON Lines (see
    app.services.training_export). It holds what customers said: admins
    only, and each download is in the audit log."""
    export = await run_in_threadpool(_training_export, service, call_service)
    return Response(
        export.content,
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": 'attachment; filename="training-data.jsonl"',
            "Cache-Control": "no-store",
        },
    )


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
    _: User = Depends(_SUPERVISORS),
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
    effect = item.effect or ImprovementEffectMeasure(ImprovementEffect.NOT_ENOUGH_DATA)
    return ActiveImprovementResponse(
        improvement_id=improvement.improvement_id,
        candidate_id=improvement.candidate_id,
        component=improvement.component,
        guidance=guidance_text(improvement.specification),
        proposed_behavior=improvement.specification.proposed_behavior,
        status=improvement.status,
        activated_at=improvement.activated_at,
        deactivated_at=improvement.deactivated_at,
        usage_count=item.effectiveness.usage_count,
        feedback_count=item.effectiveness.evidence_count,
        effectiveness_status=item.effectiveness.status,
        effect=effect.effect,
        outputs_before=effect.outputs_before,
        corrections_before=effect.corrections_before,
        outputs_after=effect.outputs_after,
        corrections_after=effect.corrections_after,
    )