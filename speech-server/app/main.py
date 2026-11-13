import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.audio import decode_audio_bytes, resample_audio
from app.auth import verify_bearer_token, verify_websocket_auth
from app.config import get_settings
from app.engine import get_engine
from app.engine.base import TranscriptionResponse
from app.vad import StreamVADProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("speech-to-text-server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Asynchronous lifespan: initializes and loads the STT engine in background."""
    settings = get_settings()
    engine = get_engine()

    # Load engine asynchronously so /health reports 503 until ready
    if not engine.is_loaded():
        loop = asyncio.get_running_loop()
        try:
            logger.info("Initializing STT model: %s...", settings.MODEL_NAME_OR_PATH)
            await loop.run_in_executor(None, engine.load)
            logger.info("STT model loaded successfully onto %s", engine.get_info().get("device"))
        except Exception as e:
            logger.error("Failed to load STT model during startup: %s", e)

    yield


app = FastAPI(
    title="Speech-to-Text Server",
    description="Automotive Call-Analysis Multilingual STT Server",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health(authenticated: bool = Depends(verify_bearer_token)):
    """Health check endpoint. Returns 503 while model is loading, 200 once ready."""
    engine = get_engine()
    if not engine.is_loaded():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "loading", "detail": "STT model is still loading"},
        )
    info = engine.get_info()
    return {
        "status": "ok",
        "model": info.get("model"),
        "device": info.get("device", "cpu"),
    }


@app.post(
    "/v1/transcribe",
    response_model=TranscriptionResponse,
    status_code=status.HTTP_200_OK,
)
async def transcribe_audio(
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    with_timestamps: str = Form("true"),
    authenticated: bool = Depends(verify_bearer_token),
):
    """
    Transcribes audio file (WAV, MP3 or raw bytes).
    Resamples to 16 kHz mono. Rejects audio > 30 s with 413.
    """
    engine = get_engine()
    if not engine.is_loaded():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STT model is still loading",
        )

    # Validate language code if provided
    valid_languages = {"ta", "en", "te", "kn", "ml"}
    if language is not None and language.strip() != "":
        lang = language.strip().lower()
        if lang not in valid_languages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported language '{language}'. Must be one of: ta, en, te, kn, ml",
            )
    else:
        lang = None

    use_timestamps = with_timestamps.lower() in ("true", "1", "yes")

    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read uploaded file: {str(e)}",
        )

    # Decode, resample to 16 kHz mono float32, and check 30 s limit
    samples, duration = decode_audio_bytes(content)

    # Transcribe via engine
    result = await engine.transcribe(
        audio=samples,
        sample_rate=16000,
        language=lang,
        with_timestamps=use_timestamps,
    )
    return result


@app.websocket("/v1/stream")
async def websocket_stream(
    websocket: WebSocket,
    language: Optional[str] = Query(None),
    sample_rate: int = Query(16000),
    pause_ms: int = Query(250),
    max_segment_seconds: float = Query(8.0),
):
    """
    Real-time streaming transcription endpoint.
    Accepts 16-bit PCM binary frames and text control frame {"type": "end"}.
    Emits speech_start, speech_end, transcript, and error frames.
    """
    # 1. Auth check
    if not await verify_websocket_auth(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
        return

    engine = get_engine()
    if not engine.is_loaded():
        await websocket.accept()
        await websocket.send_text(
            json.dumps({"type": "error", "message": "STT model is still loading"})
        )
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
        return

    await websocket.accept()

    vad_processor = StreamVADProcessor(
        sample_rate=sample_rate,
        pause_ms=pause_ms,
        max_segment_seconds=max_segment_seconds,
    )

    valid_languages = {"ta", "en", "te", "kn", "ml"}
    target_lang = language.lower() if language and language.lower() in valid_languages else None

    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message and message["bytes"]:
                raw_bytes = message["bytes"]
                events = vad_processor.process_pcm_chunk(raw_bytes)

                for event_type, event_data in events:
                    if event_type == "speech_start":
                        await websocket.send_text(
                            json.dumps({"type": "speech_start", "at": event_data["at"]})
                        )
                    elif event_type == "speech_end":
                        await websocket.send_text(
                            json.dumps({"type": "speech_end", "at": event_data["at"]})
                        )
                    elif event_type == "segment_ready":
                        chunk_audio = event_data["audio"]
                        # Resample to 16 kHz if sample_rate != 16000
                        if sample_rate != 16000:
                            chunk_audio = resample_audio(chunk_audio, sample_rate, 16000)

                        res = await engine.transcribe(
                            audio=chunk_audio,
                            sample_rate=16000,
                            language=target_lang,
                            with_timestamps=False,
                        )

                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "transcript",
                                    "text": res.transcript,
                                    "language": res.language,
                                    "start": event_data["start"],
                                    "end": event_data["end"],
                                    "confidence": res.confidence,
                                }
                            )
                        )

            elif "text" in message and message["text"]:
                try:
                    payload = json.loads(message["text"])
                except Exception:
                    await websocket.send_text(
                        json.dumps({"type": "error", "message": "Invalid JSON text frame"})
                    )
                    continue

                if payload.get("type") == "end":
                    # Flush remaining audio
                    final_events = vad_processor.finalize()
                    for event_type, event_data in final_events:
                        if event_type == "speech_end":
                            await websocket.send_text(
                                json.dumps({"type": "speech_end", "at": event_data["at"]})
                            )
                        elif event_type == "segment_ready":
                            chunk_audio = event_data["audio"]
                            if sample_rate != 16000:
                                chunk_audio = resample_audio(chunk_audio, sample_rate, 16000)

                            res = await engine.transcribe(
                                audio=chunk_audio,
                                sample_rate=16000,
                                language=target_lang,
                                with_timestamps=False,
                            )
                            await websocket.send_text(
                                json.dumps(
                                    {
                                        "type": "transcript",
                                        "text": res.transcript,
                                        "language": res.language,
                                        "start": event_data["start"],
                                        "end": event_data["end"],
                                        "confidence": res.confidence,
                                    }
                                )
                            )
                    # Gracefully close connection
                    await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
                    break
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error("Error in streaming WebSocket: %s", e)
        try:
            await websocket.send_text(
                json.dumps({"type": "error", "message": str(e)})
            )
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            pass

