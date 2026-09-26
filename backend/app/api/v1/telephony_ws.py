import json
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, WebSocket
from fastapi.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect

from app.ai.asr.provider import ASRProvider
from app.api.dependencies import (
    get_asr_provider,
    get_call_service,
    get_live_call_handler,
    get_telephony_provider,
    get_telephony_stream_flush_seconds,
    get_workflow_service,
)
from app.api.v1.live import CALL_NOT_FOUND_CLOSE_CODE
from app.api.v1.live_handler import LiveCallHandler
from app.domain.conversation import ConversationAlreadyCompletedError, ConversationStatus
from app.domain.utterance import SpeakerRole, Utterance
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.services.conversation_service import ConversationNotFoundError
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
    asr_provider: ASRProvider | None = Depends(get_asr_provider),
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

    buffer: TelephonyAudioBuffer | None = None

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
                    await _flush_and_process(
                        buffer,
                        force=True,
                        min_duration=_MIN_FLUSH_AUDIO_SECONDS,
                        call_id=call_id,
                        asr_provider=asr_provider,
                        call_service=call_service,
                        workflow_service=workflow_service,
                    )
                buffer = TelephonyAudioBuffer(
                    sample_rate=stream_event.sample_rate or 8000,
                    flush_after_seconds=flush_after_seconds,
                )

            elif stream_event.event_type == "media":
                if buffer is not None:
                    accepted = buffer.accept(stream_event.sequence, stream_event.audio or b"")
                    if accepted:
                        await _flush_and_process(
                            buffer,
                            force=False,
                            min_duration=0.0,
                            call_id=call_id,
                            asr_provider=asr_provider,
                            call_service=call_service,
                            workflow_service=workflow_service,
                        )

            elif stream_event.event_type == "stop":
                if buffer is not None:
                    await _flush_and_process(
                        buffer,
                        force=True,
                        min_duration=_MIN_FLUSH_AUDIO_SECONDS,
                        call_id=call_id,
                        asr_provider=asr_provider,
                        call_service=call_service,
                        workflow_service=workflow_service,
                    )
                    buffer = None

            # After handling any event, check whether the call ended
            # elsewhere (the status webhook) while this socket was still
            # open. Waiting indefinitely for a "stop" that may never
            # arrive would otherwise strand any further buffered audio.
            if await _call_is_completed(call_id, call_service):
                if buffer is not None:
                    await _flush_and_process(
                        buffer,
                        force=True,
                        min_duration=_MIN_FLUSH_AUDIO_SECONDS,
                        call_id=call_id,
                        asr_provider=asr_provider,
                        call_service=call_service,
                        workflow_service=workflow_service,
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
    asr_provider: ASRProvider | None,
    call_service: CallService,
    workflow_service: CallWorkflowService,
) -> None:
    try:
        chunk = buffer.flush(force=force)
    except TelephonyAudioBufferError as exc:
        # A single malformed buffer flush must never take down the whole
        # stream — drop this chunk's audio and keep the phone call alive.
        logger.warning("Dropping unencodable audio buffer for call %r: %s", call_id, exc)
        return

    if chunk is None:
        return
    if min_duration and chunk.duration < min_duration:
        return

    await _process_chunk(call_id, chunk, asr_provider, call_service, workflow_service)


async def _process_chunk(
    call_id: str,
    chunk: BufferedAudioChunk,
    asr_provider: ASRProvider | None,
    call_service: CallService,
    workflow_service: CallWorkflowService,
) -> None:
    if asr_provider is None:
        logger.error(
            "Cannot transcribe telephony audio for call %r: no ASR provider is configured.",
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
        asr_result = await run_in_threadpool(asr_provider.transcribe, chunk.audio)
    except Exception as exc:
        logger.warning("ASR transcription failed for call %r: %s", call_id, exc)
        return

    try:
        utterance = Utterance(
            utterance_id=str(uuid4()),
            transcript=asr_result.transcript,
            speaker_role=SpeakerRole.CUSTOMER,
            languages=(asr_result.detected_language,),
            start_time=chunk.start_time,
            end_time=chunk.end_time,
            confidence=asr_result.confidence,
        )
    except ValueError as exc:
        logger.warning("Skipping unusable utterance for call %r: %s", call_id, exc)
        return

    try:
        await run_in_threadpool(workflow_service.process_utterance, call_id, utterance)
    except ConversationNotFoundError:
        return
    except ConversationAlreadyCompletedError:
        # The call completed between our status check above and this point
        # (e.g. the status webhook landed mid-transcription) — drop this
        # one utterance rather than reopening a finished conversation.
        logger.info(
            "Dropping utterance for call %r: call completed mid-transcription", call_id
        )
        return
    except Exception:
        logger.exception("Workflow processing failed for call %r", call_id)