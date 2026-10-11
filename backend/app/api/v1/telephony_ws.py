import asyncio
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, WebSocket
from fastapi.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect

from app.api.dependencies import (
    get_call_recording_store,
    get_call_service,
    get_live_call_handler,
    get_live_chunk_processing_service,
    get_telephony_call_service,
    get_telephony_provider,
    get_telephony_stream_flush_seconds,
    get_workflow_service,
)
from app.ai.asr.provider import ASRResult, NoSpeechDetected
from app.ai.asr.sarvam_streaming import (
    SUPPORTED_SAMPLE_RATES,
    SarvamStreamingSession,
    StreamedSegment,
)
from app.api.v1.live import AUTH_FAILED_CLOSE_CODE, CALL_NOT_FOUND_CLOSE_CODE
from app.api.v1.live_handler import LiveCallHandler
from app.domain.conversation import ConversationAlreadyCompletedError, ConversationStatus
from app.services.audio_chunking_service import AudioChunk
from app.services.call_alerts import CallAlertService
from app.services.call_indicators import AiStatus, CallIndicators
from app.services.call_recording_store import CallRecording, CallRecordingStore
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.services.conversation_service import ConversationNotFoundError
from app.services.live_chunk_processing_service import (
    LiveChunkProcessingService,
)
from app.services.telephony_audio_buffer import (
    MAX_PROCESSING_SAMPLE_RATE,
    BufferedAudioChunk,
    Downsampler,
    TelephonyAudioBuffer,
    TelephonyAudioBufferError,
    encode_wav,
)
from app.services.telephony_call_service import (
    STREAM_HEARTBEAT_SECONDS,
    TelephonyCallService,
)
from app.core.config import get_settings
from app.observability.metrics import (
    LIVE_CHUNK_DURATION,
    LIVE_CHUNKS,
    PROVIDER_ERRORS,
    TELEPHONY_STREAMS_OPEN,
)
from app.security.stream_token import is_test_call_stream, is_valid_stream_token
from app.telephony.plivo.provider import parse_plivo_media_stream_event
from app.telephony.provider import (
    TRACKS,
    MediaStreamEvent,
    TelephonyProvider,
    TelephonyStreamError,
    track_roles,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calls", tags=["telephony-stream"])

STREAM_INTERNAL_ERROR_CLOSE_CODE = 1011
STREAM_CALL_COMPLETED_CLOSE_CODE = 1000  # normal closure: the call ended elsewhere

# Frames before "start", or using an unsupported codec, are dropped rather
# than treated as fatal — the underlying phone call must stay up
# (keepCallAlive="true") even when we can't process its audio.
_MIN_FLUSH_AUDIO_SECONDS = 0.25

# Whether the call ended elsewhere (the status webhook) is looked up at most
# this often while audio flows: media frames arrive ~50 times a second per
# track, and each lookup loads the whole call.
COMPLETION_CHECK_SECONDS = 1.0

# At the end of a stream, how long the streaming recogniser gets to answer
# for what was still being said.
STREAMING_FINISH_SECONDS = 3.0


@dataclass
class _StreamedTrack:
    """One track's audio going to the streaming recogniser."""

    session: SarvamStreamingSession
    last_sequence: int | None = None

    def accept(self, sequence: int | None) -> bool:
        """False for a frame already seen (a duplicate or a replay)."""
        if sequence is not None:
            if self.last_sequence is not None and sequence <= self.last_sequence:
                return False
            self.last_sequence = sequence
        return True


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
    recording_store: CallRecordingStore | None = Depends(get_call_recording_store),
) -> None:
    settings = get_settings()
    token = websocket.query_params.get("token")
    if settings.telephony_stream_auth_required and not is_valid_stream_token(
        token, call_id, settings
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
            recording_store,
            is_test_call=is_test_call_stream(token, call_id, settings),
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
    recording_store: CallRecordingStore | None = None,
    is_test_call: bool = False,
) -> None:

    rejection = await run_in_threadpool(handler.open, call_id)
    if rejection is not None:
        await websocket.send_json(rejection.model_dump(mode="json"))
        await websocket.close(code=CALL_NOT_FOUND_CLOSE_CODE)
        return

    # Test calls (see test_calls.py) stream Plivo-format frames whichever
    # provider is configured, or even when none is.
    parse_stream_event: Callable[[Mapping[str, Any], str | None], MediaStreamEvent] | None
    if is_test_call:
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

    await _StreamSession(
        websocket,
        call_id,
        parse_stream_event,
        call_service,
        live_chunk_processing_service,
        telephony_call_service,
        flush_after_seconds,
        recording_store,
    ).run()


class _StreamSession:
    """One open media stream of a call: buffers its audio into chunks for
    the worker, keeps the recording, and notices when the call has ended
    elsewhere."""

    def __init__(
        self,
        websocket: WebSocket,
        call_id: str,
        parse_stream_event: Callable[[Mapping[str, Any], str | None], MediaStreamEvent],
        call_service: CallService,
        live_chunk_processing_service: LiveChunkProcessingService,
        telephony_call_service: TelephonyCallService | None,
        flush_after_seconds: float,
        recording_store: CallRecordingStore | None,
    ) -> None:
        self._websocket = websocket
        self._call_id = call_id
        self._parse_stream_event = parse_stream_event
        self._call_service = call_service
        self._telephony_call_service = telephony_call_service
        self._flush_after_seconds = flush_after_seconds
        self._recording_store = recording_store
        # Encrypted recordings on disk; None when recording is off.
        self._recording_archive = getattr(websocket.app.state.services, "recording_archive", None)
        self._recording_max_seconds = get_settings().call_recording_max_seconds
        # One buffer per track when the two sides of the call arrive
        # separately, else one (key None) for the mixed audio.
        self._buffers: dict[str | None, TelephonyAudioBuffer] = {}
        # LIVE_ASR_MODE=streaming: what opens a streaming recogniser session,
        # and the tracks whose audio goes to one instead of a buffer. A
        # track whose session fails moves to a buffer for the rest of the
        # stream (see _streaming_failed).
        self._streaming_asr = getattr(websocket.app.state.services, "streaming_asr", None)
        self._streams: dict[str | None, _StreamedTrack] = {}
        # The two sides of the call arrive as separate tracks.
        self._split = False
        # Chunks are processed in order on a worker, off the receive loop: one
        # chunk can take longer to process than the websocket keepalive allows,
        # and a socket that stops reading gets dropped mid-call.
        self._worker = _ChunkWorker(
            call_id,
            call_service,
            live_chunk_processing_service,
            getattr(websocket.app.state.services, "alert_service", None),
            getattr(websocket.app.state.services, "call_indicators", None),
        )
        # The stream's audio encoding, from its "start" event.
        self._encoding: str | None = None
        self._downsampler = Downsampler(MAX_PROCESSING_SAMPLE_RATE)
        # The call's audio, transcribed again in full after the call (see
        # PostCallRetranscriptionService); None when not kept.
        self._recording: CallRecording | None = None
        self._next_completion_check = 0.0
        self._next_heartbeat = time.monotonic() + STREAM_HEARTBEAT_SECONDS

    async def run(self) -> None:
        """Serve the stream until it stops, disconnects or the call ends."""
        # While the stream is open, a terminal status waits for it to drain
        # before completing the call (see TelephonyCallService).
        if self._telephony_call_service is not None:
            self._telephony_call_service.stream_opened(self._call_id)

        try:
            while True:
                message = await self._websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return

                stream_event = self._parse(message)
                if stream_event is None:
                    continue

                if stream_event.event_type == "start":
                    await self._on_start(stream_event)
                elif stream_event.event_type == "media":
                    self._on_media(stream_event)
                elif stream_event.event_type == "stop":
                    await self._on_stop()

                if await self._call_ended_elsewhere(stream_event):
                    return
        except WebSocketDisconnect:
            return
        except Exception:
            logger.exception("Telephony stream crashed for call %r", self._call_id)
            try:
                await self._websocket.close(code=STREAM_INTERNAL_ERROR_CLOSE_CODE)
            except RuntimeError:
                pass  # socket already closed
        finally:
            # A disconnect without "stop" must not discard the call's final
            # audio. _process_chunk drops it if the call already completed.
            try:
                await self._finish_streams()
                self._flush_all(is_final=True)
                await self._worker.close()
            finally:
                self._store_recording()
                if self._telephony_call_service is not None:
                    self._telephony_call_service.stream_drained(self._call_id)

    def _parse(self, message: Mapping[str, Any]) -> MediaStreamEvent | None:
        """The stream event in a socket message; None (and a log line) for
        anything that is not one. A bad frame never ends the stream."""
        raw_text = message.get("text")
        if raw_text is None:
            logger.debug("Ignoring non-text telephony stream frame for call %r", self._call_id)
            return None

        try:
            raw_event = json.loads(raw_text)
        except json.JSONDecodeError:
            logger.warning(
                "Malformed (non-JSON) telephony stream frame for call %r", self._call_id
            )
            return None

        try:
            return self._parse_stream_event(raw_event, self._encoding)
        except TelephonyStreamError as exc:
            logger.warning("Invalid telephony stream frame for call %r: %s", self._call_id, exc)
            return None

    async def _on_start(self, stream_event: MediaStreamEvent) -> None:
        if self._telephony_call_service is not None:
            self._telephony_call_service.stream_opened(self._call_id)
        await self._finish_streams()
        # A second "start" on the same connection (e.g. a
        # provider-side stream restart) without a "stop" first
        # must not silently discard whatever was already buffered.
        self._flush_all(is_final=False)
        # The new stream's chunks and times start at 0 again (as do
        # a reconnected socket's); they carry on from the call's
        # previous ones.
        self._worker.stream_started()
        self._encoding = stream_event.encoding
        # Audio finer than the recogniser can use is brought down to 16 kHz
        # as it arrives; the chunks and the recording are made from that.
        self._downsampler = Downsampler(stream_event.sample_rate or 8000)
        if self._downsampler.converts:
            logger.info(
                "Call %r streams at %d Hz; converting to %d Hz",
                self._call_id,
                self._downsampler.source_rate,
                self._downsampler.rate,
            )
        # A call streamed as two tracks (Plivo dials the other party, see
        # PlivoTelephonyProvider.build_stream_response); who speaks on
        # which depends on who placed the call (see track_roles).
        split = set(TRACKS) <= set(stream_event.tracks)
        # A restarted stream starts its chunk times at 0 again: what was
        # recorded so far is stored as one part and a new part begins (the
        # archive joins them; see CallRecordingStore for re-transcription).
        self._store_recording()
        self._recording = (
            CallRecording(
                sample_rate=self._downsampler.rate,
                max_seconds=self._recording_max_seconds,
            )
            if (self._recording_store is not None or self._recording_archive is not None)
            else None
        )
        self._split = split
        self._buffers = {}
        for track in TRACKS if split else (None,):
            if not self._start_streaming(track):
                self._buffers[track] = self._new_buffer()
        if split:
            logger.info(
                "Call %r streams the customer and the ICR as separate tracks", self._call_id
            )

    def _new_buffer(self, start_time: float = 0.0) -> TelephonyAudioBuffer:
        settings = get_settings()
        return TelephonyAudioBuffer(
            sample_rate=self._downsampler.rate,
            flush_after_seconds=self._flush_after_seconds,
            pause_seconds=settings.plivo_stream_pause_seconds,
            min_speech_seconds=settings.plivo_stream_min_speech_seconds,
            silence_rms=settings.plivo_stream_silence_rms,
            start_time=start_time,
        )

    def _start_streaming(self, track: str | None) -> bool:
        """Send the track's audio to the streaming recogniser. False when
        that is not in use, or cannot take this stream."""
        if self._streaming_asr is None or self._downsampler.rate not in SUPPORTED_SAMPLE_RATES:
            return False
        try:
            session = self._streaming_asr(
                self._downsampler.rate,
                lambda segment: self._on_segment(track, segment),
                lambda reason: self._streaming_failed(track),
            )
            session.start()
        except Exception:
            logger.exception(
                "Could not start streaming speech recognition for call %r", self._call_id
            )
            return False
        self._streams[track] = _StreamedTrack(session)
        return True

    def _on_segment(self, track: str | None, segment: StreamedSegment) -> None:
        """The streaming recogniser heard a stretch of speech: it goes the
        way a chunk does, with its text already known."""
        if not segment.audio:
            return
        self._worker.submit(
            BufferedAudioChunk(
                audio=encode_wav(segment.audio, self._downsampler.rate),
                start_time=segment.start_time,
                end_time=segment.end_time,
                ends_on_pause=not segment.cut_short,
                continues_previous=segment.continues_previous,
                # In a language Sarvam named but this system does not take,
                # the ordinary recogniser hears the stretch again.
                transcribed=(
                    ASRResult(
                        transcript=segment.transcript,
                        detected_language=segment.language,
                        start_time=0.0,
                        end_time=segment.end_time - segment.start_time,
                    )
                    if segment.language is not None
                    else None
                ),
            ),
            False,
            track,
        )

    def _streaming_failed(self, track: str | None) -> None:
        """The track's streaming session broke: the rest of the stream is
        recognised in chunks, starting with what the session had not
        answered for."""
        stream = self._streams.pop(track, None)
        if stream is None:
            return
        PROVIDER_ERRORS.inc("asr_streaming")
        logger.warning(
            "Call %r%s carries on with chunked speech recognition",
            self._call_id,
            f" ({track} track)" if track else "",
        )
        buffer = self._new_buffer(start_time=stream.session.heard_until)
        buffer.accept(None, stream.session.unheard_audio())
        self._buffers[track] = buffer

    async def _finish_streams(self) -> None:
        """The stream is over: have the streaming recogniser answer for
        what was still being said. A session that fails here leaves its
        audio in a buffer, for the flush that follows."""
        streams = list(self._streams.values())
        if streams:
            await asyncio.gather(
                *(stream.session.finish(STREAMING_FINISH_SECONDS) for stream in streams),
                return_exceptions=True,
            )
        self._streams = {}

    def _on_media(self, stream_event: MediaStreamEvent) -> None:
        track = stream_event.track if self._split else None
        audio = self._downsampler.convert(track, stream_event.audio or b"")
        stream = self._streams.get(track)
        if stream is not None:
            if not stream.accept(stream_event.sequence):
                return
            if self._recording is not None and audio:
                self._recording.append(track, audio)
            stream.session.feed(audio)
            return
        buffer = self._buffers.get(track)
        if buffer is None:
            return
        if not buffer.accept(stream_event.sequence, audio):
            return
        if self._recording is not None and audio:
            self._recording.append(track, audio)
        _flush(buffer, self._worker, track, force=False, min_duration=0.0, is_final=False)

    async def _on_stop(self) -> None:
        await self._finish_streams()
        self._flush_all(is_final=True)
        self._buffers = {}
        await self._worker.drain()
        self._store_recording()
        # All of this stream's audio has been processed.
        if self._telephony_call_service is not None:
            self._telephony_call_service.stream_drained(self._call_id)

    async def _call_ended_elsewhere(self, stream_event: MediaStreamEvent) -> bool:
        """Whether the call ended elsewhere (the status webhook) while this
        socket was still open, in which case the socket is closed. Waiting
        indefinitely for a "stop" that may never arrive would otherwise
        strand any further buffered audio. Media frames check at most once
        per COMPLETION_CHECK_SECONDS; other events always check."""
        now = time.monotonic()
        if stream_event.event_type == "media" and now < self._next_completion_check:
            return False
        self._next_completion_check = now + COMPLETION_CHECK_SECONDS
        # Still streaming: keep the stream marked open for the other
        # instances (the mark expires if this one dies).
        if (
            (self._buffers or self._streams)
            and self._telephony_call_service is not None
            and now >= self._next_heartbeat
        ):
            self._next_heartbeat = now + STREAM_HEARTBEAT_SECONDS
            await run_in_threadpool(self._telephony_call_service.stream_opened, self._call_id)
        if not await _call_is_completed(self._call_id, self._call_service):
            return False
        await self._finish_streams()
        self._flush_all(is_final=True)
        self._buffers = {}
        await self._websocket.close(code=STREAM_CALL_COMPLETED_CLOSE_CODE)
        return True

    def _flush_all(self, *, is_final: bool) -> None:
        """Hand every buffer's audio to the worker, whatever its length
        (bar a fraction of a second, which is not worth transcribing)."""
        _flush_all(
            self._buffers,
            self._worker,
            force=True,
            min_duration=_MIN_FLUSH_AUDIO_SECONDS,
            is_final=is_final,
        )

    def _store_recording(self) -> None:
        recording, self._recording = self._recording, None
        if recording is None or not recording.tracks:
            return
        if self._recording_store is not None:
            self._recording_store.put(self._call_id, recording)
        if self._recording_archive is not None:
            # Encrypting and writing a long call takes a while: off the
            # event loop, so other calls' audio keeps flowing.
            asyncio.get_running_loop().run_in_executor(
                None, _archive_recording, self._recording_archive, self._call_id, recording
            )


def _archive_recording(archive, call_id: str, recording: CallRecording) -> None:
    try:
        archive.save(call_id, recording)
    except Exception:
        logger.exception("Could not keep the recording of call %r", call_id)


async def _call_is_completed(call_id: str, call_service: CallService) -> bool:
    try:
        conversation = await run_in_threadpool(call_service.get_call, call_id)
    except ConversationNotFoundError:
        return False
    return conversation.status == ConversationStatus.COMPLETED


# Queued between chunks: the stream (re)started (see _ChunkWorker.stream_started).
_STREAM_STARTED = object()


class _ChunkWorker:
    """Processes one stream's audio chunks, in the order submitted, on a
    background task."""

    def __init__(
        self,
        call_id: str,
        call_service: CallService,
        live_chunk_processing_service: LiveChunkProcessingService,
        alert_service: CallAlertService | None = None,
        indicators: CallIndicators | None = None,
    ) -> None:
        self.call_id = call_id
        self._alert_service = alert_service
        self._indicators = indicators
        self._call_service = call_service
        self._live_chunk_processing_service = live_chunk_processing_service
        self._queue: asyncio.Queue[
            tuple[BufferedAudioChunk, int, bool, str | None] | object | None
        ] = asyncio.Queue()
        # Each track numbers its chunks from 0, again after each "start".
        self._next_sequence: dict[str | None, int] = {}
        self._task = asyncio.create_task(self._run())

    def stream_started(self) -> None:
        """A stream (re)starts: number its chunks from 0, and tell the
        processing service once the chunks submitted before are done."""
        self._next_sequence = {}
        self._queue.put_nowait(_STREAM_STARTED)

    def submit(self, chunk: BufferedAudioChunk, is_final: bool, track: str | None = None) -> None:
        sequence = self._next_sequence.get(track, 0)
        self._queue.put_nowait((chunk, sequence, is_final, track))
        self._next_sequence[track] = sequence + 1

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
                if item is _STREAM_STARTED:
                    await run_in_threadpool(
                        self._live_chunk_processing_service.stream_started, self.call_id
                    )
                    continue
                chunk, sequence, is_final, track = item
                await _process_chunk(
                    self.call_id,
                    chunk,
                    sequence,
                    self._call_service,
                    self._live_chunk_processing_service,
                    is_final,
                    track,
                    self._alert_service,
                    self._indicators,
                )
            except Exception:
                logger.exception("Live pipeline processing failed for call %r", self.call_id)
            finally:
                self._queue.task_done()


def _flush_all(
    buffers: dict[str | None, TelephonyAudioBuffer],
    worker: _ChunkWorker,
    *,
    force: bool,
    min_duration: float,
    is_final: bool,
) -> None:
    for track, buffer in buffers.items():
        _flush(buffer, worker, track, force=force, min_duration=min_duration, is_final=is_final)


def _flush(
    buffer: TelephonyAudioBuffer,
    worker: _ChunkWorker,
    track: str | None = None,
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
    if track is not None and not chunk.has_speech:
        # One side of the call, silent while the other speaks: nothing to
        # transcribe.
        return
    worker.submit(chunk, is_final, track)


def _note_audio(
    alert_service: CallAlertService | None,
    call_id: str,
    chunk: BufferedAudioChunk,
    recognised: bool,
) -> None:
    """Tell the alerts how the audio is doing. Only stretches someone
    spoke in count: silence that transcribes to nothing is not poor audio."""
    if alert_service is not None and chunk.has_speech:
        alert_service.note_audio(call_id, recognised)


async def _process_chunk(
    call_id: str,
    chunk: BufferedAudioChunk,
    chunk_sequence: int,
    call_service: CallService,
    live_chunk_processing_service: LiveChunkProcessingService | None,
    is_final: bool,
    track: str | None = None,
    alert_service: CallAlertService | None = None,
    indicators: CallIndicators | None = None,
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

    stream = "mixed" if track is None else "tracks"
    if conversation.status == ConversationStatus.COMPLETED:
        # Call ended (via the status webhook) while audio was still
        # buffered — drop it rather than reopening a finished conversation.
        logger.info("Dropping buffered telephony audio for completed call %r", call_id)
        LIVE_CHUNKS.inc(stream, "dropped")
        return
    if conversation.on_hold:
        # Hold music, or the executive talking to someone else: not part
        # of the conversation, and not a sign of poor audio either.
        LIVE_CHUNKS.inc(stream, "on_hold")
        return

    if indicators is not None and chunk.has_speech:
        indicators.set_ai(call_id, AiStatus.TRANSCRIBING)
    try:
        await _transcribe_chunk(
            call_id, chunk, chunk_sequence, live_chunk_processing_service, is_final, track,
            alert_service, stream, conversation,
        )
    finally:
        if indicators is not None and chunk.has_speech:
            indicators.set_ai(call_id, AiStatus.LISTENING)


async def _transcribe_chunk(
    call_id: str,
    chunk: BufferedAudioChunk,
    chunk_sequence: int,
    live_chunk_processing_service: LiveChunkProcessingService,
    is_final: bool,
    track: str | None,
    alert_service: CallAlertService | None,
    stream: str,
    conversation,
) -> None:
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
                ends_on_pause=chunk.ends_on_pause,
                continues_previous=chunk.continues_previous,
                track=track,
                speaker_role=(
                    track_roles(conversation.direction).get(track) if track is not None else None
                ),
                transcribed=chunk.transcribed,
            ),
        )
    except ConversationNotFoundError:
        return
    except ConversationAlreadyCompletedError:
        logger.info(
            "Dropping telephony chunk for call %r: call completed mid-processing",
            call_id,
        )
        LIVE_CHUNKS.inc(stream, "dropped")
        return
    except NoSpeechDetected:
        _note_audio(alert_service, call_id, chunk, recognised=False)
        logger.info(
            "No speech in %.1fs of audio (call time %.1f-%.1fs) for call %r",
            chunk.duration,
            chunk.start_time,
            chunk.end_time,
            call_id,
        )
        LIVE_CHUNKS.inc(stream, "silent")
        return
    except Exception:
        logger.exception("Live pipeline processing failed for call %r", call_id)
        LIVE_CHUNKS.inc(stream, "failed")
        return
    _note_audio(alert_service, call_id, chunk, recognised=True)
    LIVE_CHUNKS.inc(stream, "transcribed")
    LIVE_CHUNK_DURATION.observe(time.monotonic() - started, stream)
    logger.info(
        "Transcribed %.1fs of %saudio (call time %.1f-%.1fs, %s) for call %r in %.1fs",
        chunk.duration,
        f"{track} " if track else "",
        chunk.start_time,
        chunk.end_time,
        "ends on a pause" if chunk.ends_on_pause else "no pause at the end",
        call_id,
        time.monotonic() - started,
    )
