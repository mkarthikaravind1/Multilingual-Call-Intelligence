from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from app.api.dependencies import (
    get_telephony_call_service,
    get_telephony_provider,
    get_workflow_service,
)
from app.core.config import get_settings
from app.security.stream_token import create_stream_token
from app.services.call_workflow_service import CallWorkflowService
from app.services.telephony_call_service import TelephonyCallService
from app.telephony.provider import TelephonyProvider, TelephonyWebhookError

router = APIRouter(prefix="/telephony/plivo", tags=["telephony"])


async def _form_params(request: Request) -> dict[str, str]:
    form = await request.form()
    return {key: str(value) for key, value in form.items()}


def _webhook_url(request: Request) -> str:
    base = get_settings().plivo_public_base_url.strip()
    if not base:
        return str(request.url)
    # As Plivo called it: the signature covers the query string too.
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{base.rstrip('/')}{request.url.path}{query}"


def _require_provider(provider: TelephonyProvider | None) -> TelephonyProvider:
    if provider is None:
        raise HTTPException(status_code=503, detail="Telephony provider is not configured.")
    return provider


@router.post("/answer")
async def plivo_answer(
    request: Request,
    provider: TelephonyProvider | None = Depends(get_telephony_provider),
    telephony_call_service: TelephonyCallService = Depends(get_telephony_call_service),
) -> Response:
    provider = _require_provider(provider)
    params = await _form_params(request)

    if not provider.validate_signature(request.headers, _webhook_url(request), params):
        raise HTTPException(status_code=403, detail="Invalid webhook signature.")

    try:
        event = provider.parse_inbound_call(params)
    except TelephonyWebhookError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    call_id = await run_in_threadpool(
        telephony_call_service.start_call_from_provider, "plivo", event
    )

    settings = get_settings()
    stream_url = (
        f"{settings.plivo_stream_base_url.rstrip('/')}"
        f"/api/v1/calls/{call_id}/telephony-stream"
        f"?token={create_stream_token(call_id, settings)}"
    )
    telephony_response = provider.build_stream_response(stream_url)

    return Response(
        content=telephony_response.content, media_type=telephony_response.content_type
    )


@router.post("/status")
async def plivo_status(
    request: Request,
    background_tasks: BackgroundTasks,
    provider: TelephonyProvider | None = Depends(get_telephony_provider),
    telephony_call_service: TelephonyCallService = Depends(get_telephony_call_service),
    workflow_service: CallWorkflowService = Depends(get_workflow_service),
) -> Response:
    provider = _require_provider(provider)
    params = await _form_params(request)

    if not provider.validate_signature(request.headers, _webhook_url(request), params):
        raise HTTPException(status_code=403, detail="Invalid webhook signature.")

    try:
        event = provider.parse_call_status(params)
    except TelephonyWebhookError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # The call's media stream is still open and may hold final buffered or
    # in-flight audio: complete after it drains, off the request path, so
    # those utterances land before post-call processing reads the call.
    if await run_in_threadpool(telephony_call_service.call_awaiting_stream_drain, event):
        background_tasks.add_task(
            telephony_call_service.complete_after_stream_drains,
            event,
            workflow_service.process_completed_call,
        )
        return Response(status_code=200)

    # Completion is quick; post-call processing (possibly an LLM summary)
    # runs after the response so the provider callback returns promptly.
    await run_in_threadpool(
        telephony_call_service.handle_status_event,
        event,
        lambda call_id: background_tasks.add_task(
            workflow_service.process_completed_call, call_id
        ),
    )
    return Response(status_code=200)