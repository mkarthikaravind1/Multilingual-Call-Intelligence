import logging

from fastapi import APIRouter, Depends, WebSocket
from fastapi.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect

from app.api.dependencies import get_live_call_handler
from app.api.v1.live import CALL_NOT_FOUND_CLOSE_CODE
from app.api.v1.live_handler import LiveCallHandler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calls", tags=["telephony-stream"])


@router.websocket("/{call_id}/telephony-stream")
async def telephony_stream(
    websocket: WebSocket,
    call_id: str,
    handler: LiveCallHandler = Depends(get_live_call_handler),
) -> None:
    # Phase 1: validate the call exists and track stream lifecycle only.
    # Media payload decoding into ASR is Phase 2.
    await websocket.accept()

    rejection = await run_in_threadpool(handler.open, call_id)
    if rejection is not None:
        await websocket.send_json(rejection.model_dump(mode="json"))
        await websocket.close(code=CALL_NOT_FOUND_CLOSE_CODE)
        return

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("text") is not None:
                logger.debug("Telephony stream frame for call %r", call_id)
    except WebSocketDisconnect:
        return