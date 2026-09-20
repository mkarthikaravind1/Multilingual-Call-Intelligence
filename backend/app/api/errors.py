from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.services.conversation_service import ConversationNotFoundError

def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ConversationNotFoundError)
    async def handle_call_not_found(
        request: Request, exc: ConversationNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def handle_domain_validation_error(
        request: Request, exc: ValueError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})