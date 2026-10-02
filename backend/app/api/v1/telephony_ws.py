import asyncio
import json
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, Depends, WebSocket
from fastapi.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect

from app.api.dependencies import (
    get_call_service,
    get_live_call_handler,
    get_live_chunk_processing_service,
    get_telephony_call_service,
    get_telephony_provider,
    get_telephony_stream_flush_seconds,
    get_workflow_service,
)
from app.api.v1.live import AUTH_FAILED_CLOSE_CODE, CALL_NOT_FOUND_CLOSE_CODE
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
from app.services.telephony_call_service import TelephonyCallService
from app.core.config import get_settings
from app.observability.metrics import TELEPHONY_STREAMS_OPEN
from app.security.stream_token import is_valid_stream_token
from app.telephony.plivo.provider import parse_plivo_media_stream_event
from app.telephony.provider import MediaStreamEvent, TelephonyStreamError, TelephonyProvider
from app.api.v1.test_calls import TEST_PROVIDER

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
    telephony_call_service: TelephonyCallService | None = Depends(
        get_telephony_call_service
    ),
    flush_after_seconds: float = Depends(get_telephony_stream_flush_seconds),
) -> None:
    settings = get_settings()
    if settings.telephony_stream_auth_required and not is_valid_stream_token(
        websocket.query_params.get("token"), call_id, settings
    ):
        logger.warning("Rejected telephony stream for call %r: missing or invalid token", call_id)
        await websocket.close(code=AUTH_FAILED_CLOSE_CODE)
        return

    await websocket.accept()
    TELEPHONY_STREAMS_OPEN.inc()
    try:
        await _serve_stream(
            websocket,
            call_id,
            handler,
            provider,
            live_chunk_processing_service,
            call_service,
            telephony_call_service,
            flush_after_seconds,
        )
    finally:
        TELEPHONY_STREAMS_OPEN.dec()


async def _serve_stream(
    websocket: WebSocket,
    call_id: str,
    handler: LiveCallHandler,
    provider: TelephonyProvider | None,
    live_chunk_processing_service: LiveChunkProcessingService | None,
    call_service: CallService,
    telephony_call_service: TelephonyCallService | None,
    flush_after_seconds: float,
) -> None:

    rejection = await run_in_threadpool(handler.open, call_id)
    if rejection is not None:
        await websocket.send_json(rejection.model_dump(mode="json"))
        await websocket.close(code=CALL_NOT_FOUND_CLOSE_CODE)
        return

    # Test calls (see test_calls.py) stream Plivo-format frames whichever
    # provider is configured, or even when none is.
    parse_stream_event: Callable[[Mapping[str, Any]], MediaStreamEvent] | None
    if call_id.startswith(f"{TEST_PROVIDER}-"):
        parse_stream_event = parse_plivo_media_stream_event
    elif provider is not None:
        parse_stream_event = provider.parse_media_stream_event
    else:
        parse_stream_event = None

    if parse_stream_event is None:
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
    # Chunks are processed in order on a worker, off this receive loop: one
    # chunk can take longer to process than the websocket keepalive allows,
    # and a socket that stops reading gets dropped mid-call.
    worker = _ChunkWorker(call_id, call_service, live_chunk_processing_service)

    # While the stream is open, a terminal status waits for it to drain
    # before completing the call (see TelephonyCallService).
    if telephony_call_service is not None:
        telephony_call_service.stream_opened(call_id)

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
                stream_event = parse_stream_event(raw_event)
            except TelephonyStreamError as exc:
                logger.warning("Invalid telephony stream frame for call %r: %s", call_id, exc)
                continue

            if stream_event.event_type == "start":
                if telephony_call_service is not None:
                    telephony_call_service.stream_opened(call_id)
                if buffer is not None:
                    # A second "start" on the same connection (e.g. a
                    # provider-side stream restart) without a "stop" first
                    # must not silently discard whatever was already buffered.
                    _flush(buffer, worker, force=True, min_duration=_MIN_FLUSH_AUDIO_SECONDS, is_final=False)
                settings = get_settings()
                buffer = TelephonyAudioBuffer(
                    sample_rate=stream_event.sample_rate or 8000,
                    flush_after_seconds=flush_after_seconds,
                    pause_seconds=settings.plivo_stream_pause_seconds,
                    min_speech_seconds=settings.plivo_stream_min_speech_seconds,
                    silence_rms=settings.plivo_stream_silence_rms,
                )

            elif stream_event.event_type == "media":
                if buffer is not None:
                    accepted = buffer.accept(stream_event.sequence, stream_event.audio or b"")
                    if accepted:
                        _flush(buffer, worker, force=False, min_duration=0.0, is_final=False)

            elif stream_event.event_type == "stop":
                if buffer is not None:
                    _flush(buffer, worker, force=True, min_duration=_MIN_FLUSH_AUDIO_SECONDS, is_final=True)
                    buffer = None
                await worker.drain()
                # All of this stream's audio has been processed.
                if telephony_call_service is not None:
                    telephony_call_service.stream_drained(call_id)

            # After handling any event, check whether the call ended
            # elsewhere (the status webhook) while this socket was still
            # open. Waiting indefinitely for a "stop" that may never
            # arrive would otherwise strand any further buffered audio.
            if await _call_is_completed(call_id, call_service):
                if buffer is not None:
                    _flush(buffer, worker, force=True, min_duration=_MIN_FLUSH_AUDIO_SECONDS, is_final=True)
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
    finally:
        # A disconnect without "stop" must not discard the call's final
        # audio. _process_chunk drops it if the call already completed.
        try:
            if buffer is not None:
                _flush(buffer, worker, force=True, min_duration=_MIN_FLUSH_AUDIO_SECONDS, is_final=True)
            await worker.close()
        finally:
            if telephony_call_service is not None:
                telephony_call_service.stream_drained(call_id)


async def _call_is_completed(call_id: str, call_service: CallService) -> bool:
    try:
        conversation = await run_in_threadpool(call_service.get_call, call_id)
    except ConversationNotFoundError:
        return False
    return conversation.status == ConversationStatus.COMPLETED


class _ChunkWorker:
    """Processes one stream's audio chunks, in the order submitted, on a
    background task."""

    def __init__(
        self,
        call_id: str,
        call_service: CallService,
        live_chunk_processing_service: LiveChunkProcessingService,
    ) -> None:
        self.call_id = call_id
        self._call_service = call_service
        self._live_chunk_processing_service = live_chunk_processing_service
        self._queue: asyncio.Queue[tuple[BufferedAudioChunk, int, bool] | None] = asyncio.Queue()
        self._next_sequence = 0
        self._task = asyncio.create_task(self._run())

    def submit(self, chunk: BufferedAudioChunk, is_final: bool) -> None:
        self._queue.put_nowait((chunk, self._next_sequence, is_final))
        self._next_sequence += 1

    async def drain(self) -> None:
        """Wait until every chunk submitted so far has been processed."""
        await self._queue.join()

    async def close(self) -> None:
        """Process everything submitted, then stop."""
        self._queue.put_nowait(None)
        await self._task

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is None:
                    return
                chunk, sequence, is_final = item
                await _process_chunk(
                    self.call_id,
                    chunk,
                    sequence,
                    self._call_service,
                    self._live_chunk_processing_service,
                    is_final,
                )
            except Exception:
                logger.exception("Live pipeline processing failed for call %r", self.call_id)
            finally:
                self._queue.task_done()


def _flush(
    buffer: TelephonyAudioBuffer,
    worker: _ChunkWorker,
    *,
    force: bool,
    min_duration: float,
    is_final: bool,
) -> None:
    try:
        chunk = buffer.flush(force=force)
    except TelephonyAudioBufferError as exc:
        # A single malformed buffer flush must never take down the whole
        # stream — drop this chunk's audio and keep the phone call alive.
        logger.warning("Dropping unencodable audio buffer for call %r: %s", worker.call_id, exc)
        return

    if chunk is None:
        return
    if min_duration and chunk.duration < min_duration:
        return
    worker.submit(chunk, is_final)


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

    started = time.monotonic()
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
        return
    logger.info(
        "Transcribed %.1fs of audio (call time %.1f-%.1fs) for call %r in %.1fs",
        chunk.duration,
        chunk.start_time,
        chunk.end_time,
        call_id,
        time.monotonic() - started,
    )
