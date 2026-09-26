from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.dependencies import get_telephony_call_service, get_telephony_provider
from app.core.config import get_settings
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
    return f"{base.rstrip('/')}{request.url.path}"


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

    call_id = telephony_call_service.start_call_from_provider("plivo", event)

    settings = get_settings()
    stream_url = (
        f"{settings.plivo_stream_base_url.rstrip('/')}"
        f"/api/v1/calls/{call_id}/telephony-stream"
    )
    telephony_response = provider.build_stream_response(stream_url)

    return Response(
        content=telephony_response.content, media_type=telephony_response.content_type
    )


@router.post("/status")
async def plivo_status(
    request: Request,
    provider: TelephonyProvider | None = Depends(get_telephony_provider),
    telephony_call_service: TelephonyCallService = Depends(get_telephony_call_service),
) -> Response:
    provider = _require_provider(provider)
    params = await _form_params(request)

    if not provider.validate_signature(request.headers, _webhook_url(request), params):
        raise HTTPException(status_code=403, detail="Invalid webhook signature.")

    try:
        event = provider.parse_call_status(params)
    except TelephonyWebhookError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    telephony_call_service.handle_status_event(event)
    return Response(status_code=200)