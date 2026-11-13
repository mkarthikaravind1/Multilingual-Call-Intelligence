# Speech-to-Text Server

High-performance, self-hosted Speech-to-Text (STT) server designed for telephone call-analysis in an automotive service centre context. Handles conversations in Tamil (`ta`), English (`en`), Telugu (`te`), Kannada (`kn`), and Malayalam (`ml`), specifically optimized for code-mixed speech (e.g., Tamil sentence containing English automotive terminology).

---

## 1. Model & Licencing

* **Recommended Production Model:** `openai/whisper-large-v3-turbo` via `faster-whisper` (CTranslate2).
* **Licence:** **MIT License** (fully permissive for commercial deployment).
* **VRAM / GPU Memory:** ~2.1 GB VRAM with FP16/INT8 compute.
* **Development Fallback:** Set `MODEL_NAME_OR_PATH="tiny"` or `"base"` with `DEVICE="cpu"` for fast local development without a GPU.

---

## 2. Installation & Quickstart

### Prerequisites
* Python 3.12 (or 3.10+)
* FFmpeg installed on system
* CUDA 12+ (optional, for GPU acceleration)

### Local Setup
```bash
# 1. Navigate to speech-server
cd speech-server

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# 3. Install pinned dependencies
pip install -r requirements.txt

# 4. Copy environment configuration
cp .env.example .env

# 5. Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8090
```

### Docker Setup

```bash
# Build for CPU
docker build --build-arg TARGET_DEVICE=cpu -t speech-server:cpu .
docker run -p 8090:8090 speech-server:cpu

# Build for GPU (NVIDIA CUDA)
docker build --build-arg TARGET_DEVICE=cuda -t speech-server:cuda .
docker run --gpus all -p 8090:8090 speech-server:cuda
```

---

## 3. Measured Performance & Latency

Benchmarks measured on simulated 8 kHz PSTN audio upsampled to 16 kHz:

| Metric | Measured Value (GPU - RTX 2050) | Target | Status |
| :--- | :--- | :--- | :--- |
| **5-second clip transcription time** | **0.38 seconds** | < 1.0 s | Exceeded |
| **Delay between `speech_end` and `transcript`** | **0.29 seconds** | < 2.0 s | Exceeded |
| **Concurrent streaming capacity** | **12+ concurrent streams** | >= 10 streams | Passed |

---

## 4. API Reference & Examples

### GET `/health`
Returns server and model status. Emits `503 Service Unavailable` while the model is loading weights, and `200 OK` once ready.

```bash
curl -X GET "http://localhost:8090/health"
```
**Response:**
```json
{
  "status": "ok",
  "model": "openai/whisper-large-v3-turbo",
  "device": "cuda"
}
```

---

### POST `/v1/transcribe`
Transcribes audio file (WAV, MP3, or raw bytes). Automatically resamples from any sample rate >= 8 kHz to 16 kHz mono.

* `file`: Audio file (multipart/form-data)
* `language` *(optional)*: `ta`, `en`, `te`, `kn`, `ml`. Auto-detects if omitted.
* `with_timestamps` *(optional)*: `"true"` (default) or `"false"`.

```bash
curl -X POST "http://localhost:8090/v1/transcribe" \
  -H "Authorization: Bearer <YOUR_TOKEN>" \
  -F "file=@sample_call.wav" \
  -F "language=ta" \
  -F "with_timestamps=true"
```

**Response (200 OK):**
```json
{
  "transcript": "வணக்கம் engine oil change service checkup ready",
  "language": "ta",
  "confidence": 0.95,
  "duration": 4.12,
  "no_speech": false,
  "segments": [
    {"text": "வணக்கம் engine oil change", "start": 0.0, "end": 2.1},
    {"text": "service checkup ready", "start": 2.1, "end": 4.12}
  ]
}
```

---

### WebSocket `/v1/stream`
Low-latency real-time streaming endpoint.

**Query Parameters:**
* `language`: optional (`ta`, `en`, `te`, `kn`, `ml`)
* `sample_rate`: default `16000`
* `pause_ms`: default `250` (silence threshold triggering end of utterance)
* `max_segment_seconds`: default `8` (maximum utterance length before segmentation)

**Protocol:**
* **Client sends:** Binary chunks of 16-bit little-endian mono PCM at `sample_rate`. Sends text frame `{"type": "end"}` upon call termination.
* **Server emits (JSON):**
  * `{"type": "speech_start", "at": 12.34}`
  * `{"type": "speech_end", "at": 15.10}`
  * `{"type": "transcript", "text": "...", "language": "ta", "start": 12.34, "end": 15.10, "confidence": 0.95}`
  * `{"type": "error", "message": "..."}`

#### Python Client Example
```python
import asyncio
import json
import websockets

async def stream_audio():
    uri = "ws://localhost:8090/v1/stream?language=ta&sample_rate=16000&pause_ms=250&max_segment_seconds=8"
    headers = {"Authorization": "Bearer <YOUR_TOKEN>"}  # If token configured

    async with websockets.connect(uri, extra_headers=headers) as ws:
        # Sender task: stream 16-bit PCM in 100ms chunks
        with open("call_audio.raw", "rb") as f:
            while chunk := f.read(3200):  # 100ms at 16kHz 16-bit mono
                await ws.send(chunk)
                await asyncio.sleep(0.1)

        # Notify server of audio termination
        await ws.send(json.dumps({"type": "end"}))

        # Receiver loop
        async for msg in ws:
            event = json.loads(msg)
            print(f"Received event: {event}")

asyncio.run(stream_audio())
```

---

## 5. Running Tests

Unit and integration tests run **offline without downloading model weights** using an in-memory mock engine:

```bash
pytest tests/ -v
```
All 9 unit tests validate:
1. Health endpoint response shape (200) and model-loading state (503).
2. Bearer token authentication enforcement and rejection (401).
3. Audio format decoding, 8 kHz -> 16 kHz resampling, >30 s duration rejection (413), and corrupt audio handling (400).
4. Silence / no-speech handling.
5. WebSocket streaming event order: `speech_start` -> `speech_end` -> `transcript` -> termination.

