import asyncio

from fastapi import APIRouter, Depends, WebSocket
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect

from app.api.dependencies import get_call_service, get_live_call_handler
from app.api.v1.live_handler import LiveCallHandler
from app.api.security_dependencies import authenticate_live_call_ws, get_current_user
from app.domain.user import User
from app.security.stream_token import create_live_call_ticket
from app.services.call_service import CallService


router = APIRouter(prefix="/calls", tags=["live"])

CALL_NOT_FOUND_CLOSE_CODE = 4404
AUTH_FAILED_CLOSE_CODE = 4401


class LiveCallTicketResponse(BaseModel):
    token: str
    expires_in: int


@router.post("/{call_id}/live-token", response_model=LiveCallTicketResponse)
def create_live_token(
    call_id: str,
    call_service: CallService = Depends(get_call_service),
    user: User = Depends(get_current_user),
) -> LiveCallTicketResponse:
    """A single-use, one-minute ticket for opening this call's live
    WebSocket, so the access token never goes into a URL."""
    call_service.get_call(call_id)  # 404 for an unknown call
    ticket = create_live_call_ticket(user.user_id, call_id)
    return LiveCallTicketResponse(token=ticket.token, expires_in=ticket.expires_in)


@router.websocket("/{call_id}/live")
async def live_call(
    websocket: WebSocket,
    call_id: str,
    handler: LiveCallHandler = Depends(get_live_call_handler),
) -> None:
    user = await run_in_threadpool(authenticate_live_call_ws, websocket, call_id)
    # Accept before closing: a socket closed during the handshake reaches
    # the browser as a generic failure, and the client must be able to
    # tell "not authorised" (do not retry) from a dropped connection.
    await websocket.accept()
    if user is None:
        await websocket.close(code=AUTH_FAILED_CLOSE_CODE)
        return

    rejection = await run_in_threadpool(handler.open, call_id)
    if rejection is not None:
        await websocket.send_json(rejection.model_dump(mode="json"))
        await websocket.close(code=CALL_NOT_FOUND_CLOSE_CODE)
        return

    # One loop both answers the client's utterances and, between them,
    # pushes analysis produced elsewhere: speech from the telephony stream
    # or another API instance changes the call's revision in the shared
    # live state, and the new analysis is sent whenever it does.
    interval = websocket.app.state.services.live_call_push_interval_seconds
    seen_revision = await run_in_threadpool(handler.revision, call_id)
    pending_receive: asyncio.Future | None = None
    try:
        while True:
            if pending_receive is None:
                pending_receive = asyncio.ensure_future(websocket.receive())
            # Waiting with a timeout never cancels the receive, so no message is lost.
            done, _ = await asyncio.wait({pending_receive}, timeout=interval)
            if pending_receive in done:
                message = pending_receive.result()
                pending_receive = None
                if message["type"] == "websocket.disconnect":
                    return
                event = await run_in_threadpool(handler.handle, call_id, message.get("text"))
                # The client's own utterance is answered here; don't push it again.
                seen_revision = await run_in_threadpool(handler.revision, call_id)
                await websocket.send_json(event.model_dump(mode="json"))
                continue

            revision = await run_in_threadpool(handler.revision, call_id)
            if revision != seen_revision:
                seen_revision = revision
                event = await run_in_threadpool(handler.snapshot, call_id)
                await websocket.send_json(event.model_dump(mode="json"))
    except WebSocketDisconnect:
        return
    finally:
        if pending_receive is not None:
            pending_receive.cancel()
