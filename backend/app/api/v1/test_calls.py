"""Test calls: replay a recorded conversation through the real telephony path.

The browser plays the part of the telephony provider. It starts a call here
(as if an inbound call had been answered), streams the recording to the
call's telephony stream in real time as mu-law frames, then ends the call
here (as if the provider had reported the hang-up). Everything in between —
live transcription, diarization, analysis, escalations, caller lookup and
post-call processing — is the production code path.

Disabled when APP_ENV=production.
"""

from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_telephony_call_service, get_workflow_service
from app.api.security_dependencies import require_roles
from app.core.config import get_settings
from app.domain.user import User, UserRole
from app.security.stream_token import create_stream_token
from app.services.call_workflow_service import CallWorkflowService
from app.services.telephony_call_service import TelephonyCallService
from app.telephony.provider import CallProviderStatus, CallStatusEvent, InboundCallEvent

router = APIRouter(prefix="/test-calls", tags=["test-calls"])

TEST_PROVIDER = "test"
_TEST_LINE_NUMBER = "test-line"
_SUPERVISORS = require_roles(UserRole.SUPERVISOR, UserRole.ADMIN)


def _require_enabled() -> None:
    if get_settings().is_production:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


class StartTestCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_number: str = Field(default="", max_length=32)


class StartTestCallResponse(BaseModel):
    call_id: str
    provider_call_id: str
    stream_path: str


class EndTestCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_seconds: float | None = Field(default=None, ge=0)


@router.post(
    "",
    response_model=StartTestCallResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_require_enabled)],
)
async def start_test_call(
    request: StartTestCallRequest,
    telephony_call_service: TelephonyCallService = Depends(get_telephony_call_service),
    _: User = Depends(_SUPERVISORS),
) -> StartTestCallResponse:
    provider_call_id = f"{TEST_PROVIDER}-{uuid4()}"
    event = InboundCallEvent(
        provider_call_id=provider_call_id,
        from_number=request.from_number.strip(),
        to_number=_TEST_LINE_NUMBER,
    )
    call_id = await run_in_threadpool(
        telephony_call_service.start_call_from_provider, TEST_PROVIDER, event
    )
    token = create_stream_token(call_id, get_settings())
    return StartTestCallResponse(
        call_id=call_id,
        provider_call_id=provider_call_id,
        stream_path=f"/api/v1/calls/{call_id}/telephony-stream?token={token}",
    )


@router.post(
    "/{provider_call_id}/end",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(_require_enabled)],
)
async def end_test_call(
    provider_call_id: str,
    request: EndTestCallRequest,
    background_tasks: BackgroundTasks,
    telephony_call_service: TelephonyCallService = Depends(get_telephony_call_service),
    workflow_service: CallWorkflowService = Depends(get_workflow_service),
    _: User = Depends(_SUPERVISORS),
) -> Response:
    if not provider_call_id.startswith(f"{TEST_PROVIDER}-"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not a test call.")
    if await run_in_threadpool(telephony_call_service.resolve_call_id, provider_call_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test call not found.")

    event = CallStatusEvent(
        provider_call_id=provider_call_id,
        status=CallProviderStatus.COMPLETED,
        duration_seconds=request.duration_seconds,
    )

    # Same as the provider's hang-up callback: let the stream land its final
    # audio first, then complete the call and run post-call processing.
    if await run_in_threadpool(telephony_call_service.call_awaiting_stream_drain, event):
        background_tasks.add_task(
            telephony_call_service.complete_after_stream_drains,
            event,
            workflow_service.process_completed_call,
        )
    else:
        await run_in_threadpool(
            telephony_call_service.handle_status_event,
            event,
            lambda call_id: background_tasks.add_task(
                workflow_service.process_completed_call, call_id
            ),
        )
    return Response(status_code=status.HTTP_202_ACCEPTED)
