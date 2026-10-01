from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.domain.conversation import ConversationAlreadyExistsError
from app.domain.escalation import EscalationTransitionError
from app.services.escalation_service import EscalationNotFoundError
from app.domain.emerging_complaint_candidate import EmergingComplaintReviewError
from app.services.complaint_lifecycle_service import (
    ComplaintActionError,
    ComplaintLifecycleNotFoundError,
)
from app.services.emerging_complaint_service import EmergingComplaintNotFoundError
from app.services.post_call_repair_service import CallNotRepairableError
from app.services.user_management_service import UserManagementError, UserNotFoundError
from app.services.conversation_service import ConversationNotFoundError
from app.services.improvement_application_service import ActiveImprovementNotFoundError
from app.services.learning_management_service import (
    CandidateNotFoundError,
    CandidateReviewConflictError,
    LearningFeedbackConflictError,
)
from app.services.learning_observation_service import LearningObservationNotFoundError

def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ConversationNotFoundError)
    async def handle_call_not_found(
        request: Request, exc: ConversationNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConversationAlreadyExistsError)
    async def handle_call_already_exists(
        request: Request, exc: ConversationAlreadyExistsError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(CandidateNotFoundError)
    async def handle_candidate_not_found(
        request: Request, exc: CandidateNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(CandidateReviewConflictError)
    async def handle_candidate_review_conflict(
        request: Request, exc: CandidateReviewConflictError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(LearningObservationNotFoundError)
    async def handle_observation_not_found(
        request: Request, exc: LearningObservationNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ActiveImprovementNotFoundError)
    async def handle_improvement_not_found(
        request: Request, exc: ActiveImprovementNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(LearningFeedbackConflictError)
    async def handle_feedback_conflict(
        request: Request, exc: LearningFeedbackConflictError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(EscalationNotFoundError)
    async def handle_escalation_not_found(
        request: Request, exc: EscalationNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(EscalationTransitionError)
    async def handle_escalation_transition(
        request: Request, exc: EscalationTransitionError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ComplaintLifecycleNotFoundError)
    async def handle_complaint_not_found(
        request: Request, exc: ComplaintLifecycleNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ComplaintActionError)
    async def handle_complaint_action(
        request: Request, exc: ComplaintActionError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(EmergingComplaintNotFoundError)
    async def handle_emerging_complaint_not_found(
        request: Request, exc: EmergingComplaintNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(EmergingComplaintReviewError)
    async def handle_emerging_complaint_review(
        request: Request, exc: EmergingComplaintReviewError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(UserNotFoundError)
    async def handle_user_not_found(request: Request, exc: UserNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(UserManagementError)
    async def handle_user_management(
        request: Request, exc: UserManagementError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(CallNotRepairableError)
    async def handle_call_not_repairable(
        request: Request, exc: CallNotRepairableError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def handle_domain_validation_error(
        request: Request, exc: ValueError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})