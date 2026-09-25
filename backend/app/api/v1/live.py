from fastapi import APIRouter, Depends, WebSocket
from fastapi.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect

from app.api.dependencies import get_live_call_handler
from app.api.v1.live_handler import LiveCallHandler
from app.api.security_dependencies import get_current_user_ws
router = APIRouter(prefix="/calls", tags=["live"])

CALL_NOT_FOUND_CLOSE_CODE = 4404
AUTH_FAILED_CLOSE_CODE = 4401

@router.websocket("/{call_id}/live")
async def live_call(
    websocket: WebSocket,
    call_id: str,
    handler: LiveCallHandler = Depends(get_live_call_handler),
) -> None:
    user = get_current_user_ws(websocket)
    if user is None:
        await websocket.close(code=AUTH_FAILED_CLOSE_CODE)
        return

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
            event = await run_in_threadpool(handler.handle, call_id, message.get("text"))
            await websocket.send_json(event.model_dump(mode="json"))
    except WebSocketDisconnect:
        return