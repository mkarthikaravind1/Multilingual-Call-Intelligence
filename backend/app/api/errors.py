from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.services.conversation_service import ConversationNotFoundError
from app.services.learning_management_service import (
    CandidateNotFoundError,
    CandidateReviewConflictError,
)

def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ConversationNotFoundError)
    async def handle_call_not_found(
        request: Request, exc: ConversationNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

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

    @app.exception_handler(ValueError)
    async def handle_domain_validation_error(
        request: Request, exc: ValueError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})