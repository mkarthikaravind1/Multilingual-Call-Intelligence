import json
import logging

from fastapi import APIRouter, Depends, WebSocket
from fastapi.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect

from app.api.dependencies import (
    get_call_service,
    get_live_call_handler,
    get_live_chunk_processing_service,
    get_telephony_provider,
    get_telephony_stream_flush_seconds,
    get_workflow_service,
)
from app.api.v1.live import CALL_NOT_FOUND_CLOSE_CODE
from app.api.v1.live_handler import LiveCallHandler
from app.domain.conversation import ConversationAlreadyCompletedError, ConversationStatus
from app.services.audio_chunking_service import AudioChunk
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.services.conversation_service import ConversationNotFoundError
from app.services.live_chunk_processing_service import (
    LiveChunkProcessingService,
)
from app.services.telephony_audio_buffer import (
    BufferedAudioChunk,
    TelephonyAudioBuffer,
    TelephonyAudioBufferError,
)
from app.telephony.provider import TelephonyProvider, TelephonyStreamError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calls", tags=["telephony-stream"])

STREAM_INTERNAL_ERROR_CLOSE_CODE = 1011
STREAM_CALL_COMPLETED_CLOSE_CODE = 1000  # normal closure: the call ended elsewhere

# Frames before "start", or using an unsupported codec, are dropped rather
# than treated as fatal — the underlying phone call must stay up
# (keepCallAlive="true") even when we can't process its audio.
_MIN_FLUSH_AUDIO_SECONDS = 0.25


@router.websocket("/{call_id}/telephony-stream")
async def telephony_stream(
    websocket: WebSocket,
    call_id: str,
    handler: LiveCallHandler = Depends(get_live_call_handler),
    provider: TelephonyProvider | None = Depends(get_telephony_provider),
    live_chunk_processing_service: LiveChunkProcessingService | None = Depends(
        get_live_chunk_processing_service
    ),
    call_service: CallService = Depends(get_call_service),
    workflow_service: CallWorkflowService = Depends(get_workflow_service),
    flush_after_seconds: float = Depends(get_telephony_stream_flush_seconds),
) -> None:
    await websocket.accept()

    rejection = await run_in_threadpool(handler.open, call_id)
    if rejection is not None:
        await websocket.send_json(rejection.model_dump(mode="json"))
        await websocket.close(code=CALL_NOT_FOUND_CLOSE_CODE)
        return

    if provider is None:
        logger.error(
            "Telephony stream for call %r cannot be processed: no telephony provider is configured.",
            call_id,
        )
        await websocket.close(code=STREAM_INTERNAL_ERROR_CLOSE_CODE)
        return

    if live_chunk_processing_service is None:
        logger.error(
            "Telephony stream for call %r cannot be processed: live audio pipeline is unavailable.",
            call_id,
        )
        await websocket.close(code=STREAM_INTERNAL_ERROR_CLOSE_CODE)
        return

    buffer: TelephonyAudioBuffer | None = None
    next_chunk_sequence = 0

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return

            raw_text = message.get("text")
            if raw_text is None:
                logger.debug("Ignoring non-text telephony stream frame for call %r", call_id)
                continue

            try:
                raw_event = json.loads(raw_text)
            except json.JSONDecodeError:
                logger.warning("Malformed (non-JSON) telephony stream frame for call %r", call_id)
                continue

            try:
                stream_event = provider.parse_media_stream_event(raw_event)
            except TelephonyStreamError as exc:
                logger.warning("Invalid telephony stream frame for call %r: %s", call_id, exc)
                continue

            if stream_event.event_type == "start":
                if buffer is not None:
                    # A second "start" on the same connection (e.g. a
                    # provider-side stream restart) without a "stop" first
                    # must not silently discard whatever was already buffered.
                    next_chunk_sequence = await _flush_and_process(
                        buffer,
                        force=True,
                        min_duration=_MIN_FLUSH_AUDIO_SECONDS,
                        call_id=call_id,
                        chunk_sequence=next_chunk_sequence,
                        call_service=call_service,
                        live_chunk_processing_service=live_chunk_processing_service,
                        is_final=False,
                    )
                buffer = TelephonyAudioBuffer(
                    sample_rate=stream_event.sample_rate or 8000,
                    flush_after_seconds=flush_after_seconds,
                )

            elif stream_event.event_type == "media":
                if buffer is not None:
                    accepted = buffer.accept(stream_event.sequence, stream_event.audio or b"")
                    if accepted:
                        next_chunk_sequence = await _flush_and_process(
                            buffer,
                            force=False,
                            min_duration=0.0,
                            call_id=call_id,
                            chunk_sequence=next_chunk_sequence,
                            call_service=call_service,
                            live_chunk_processing_service=live_chunk_processing_service,
                            is_final=False,
                        )

            elif stream_event.event_type == "stop":
                if buffer is not None:
                    next_chunk_sequence = await _flush_and_process(
                        buffer,
                        force=True,
                        min_duration=_MIN_FLUSH_AUDIO_SECONDS,
                        call_id=call_id,
                        chunk_sequence=next_chunk_sequence,
                        call_service=call_service,
                        live_chunk_processing_service=live_chunk_processing_service,
                        is_final=True,
                    )
                    buffer = None

            # After handling any event, check whether the call ended
            # elsewhere (the status webhook) while this socket was still
            # open. Waiting indefinitely for a "stop" that may never
            # arrive would otherwise strand any further buffered audio.
            if await _call_is_completed(call_id, call_service):
                if buffer is not None:
                    next_chunk_sequence = await _flush_and_process(
                        buffer,
                        force=True,
                        min_duration=_MIN_FLUSH_AUDIO_SECONDS,
                        call_id=call_id,
                        chunk_sequence=next_chunk_sequence,
                        call_service=call_service,
                        live_chunk_processing_service=live_chunk_processing_service,
                        is_final=True,
                    )
                    buffer = None
                await websocket.close(code=STREAM_CALL_COMPLETED_CLOSE_CODE)
                return
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("Telephony stream crashed for call %r", call_id)
        try:
            await websocket.close(code=STREAM_INTERNAL_ERROR_CLOSE_CODE)
        except RuntimeError:
            pass  # socket already closed


async def _call_is_completed(call_id: str, call_service: CallService) -> bool:
    try:
        conversation = await run_in_threadpool(call_service.get_call, call_id)
    except ConversationNotFoundError:
        return False
    return conversation.status == ConversationStatus.COMPLETED


async def _flush_and_process(
    buffer: TelephonyAudioBuffer,
    *,
    force: bool,
    min_duration: float,
    call_id: str,
    chunk_sequence: int,
    call_service: CallService,
    live_chunk_processing_service: LiveChunkProcessingService | None,
    is_final: bool,
) -> int:
    try:
        chunk = buffer.flush(force=force)
    except TelephonyAudioBufferError as exc:
        # A single malformed buffer flush must never take down the whole
        # stream — drop this chunk's audio and keep the phone call alive.
        logger.warning("Dropping unencodable audio buffer for call %r: %s", call_id, exc)
        return chunk_sequence

    if chunk is None:
        return chunk_sequence
    if min_duration and chunk.duration < min_duration:
        return chunk_sequence

    await _process_chunk(
        call_id,
        chunk,
        chunk_sequence,
        call_service,
        live_chunk_processing_service,
        is_final,
    )
    return chunk_sequence + 1


async def _process_chunk(
    call_id: str,
    chunk: BufferedAudioChunk,
    chunk_sequence: int,
    call_service: CallService,
    live_chunk_processing_service: LiveChunkProcessingService | None,
    is_final: bool,
) -> None:
    if live_chunk_processing_service is None:
        logger.error(
            "Cannot process telephony audio for call %r: live chunk processing is not configured.",
            call_id,
        )
        return

    try:
        conversation = await run_in_threadpool(call_service.get_call, call_id)
    except ConversationNotFoundError:
        return  # call record vanished mid-stream; nothing to attach audio to

    if conversation.status == ConversationStatus.COMPLETED:
        # Call ended (via the status webhook) while audio was still
        # buffered — drop it rather than reopening a finished conversation.
        logger.info("Dropping buffered telephony audio for completed call %r", call_id)
        return

    try:
        await run_in_threadpool(
            live_chunk_processing_service.process_chunk,
            call_id,
            AudioChunk(
                sequence=chunk_sequence,
                start_time=chunk.start_time,
                end_time=chunk.end_time,
                audio=chunk.audio,
                is_final=is_final,
            ),
        )
    except ConversationNotFoundError:
        return
    except ConversationAlreadyCompletedError:
        logger.info(
            "Dropping telephony chunk for call %r: call completed mid-processing",
            call_id,
        )
        return
    except Exception:
        logger.exception("Live pipeline processing failed for call %r", call_id)