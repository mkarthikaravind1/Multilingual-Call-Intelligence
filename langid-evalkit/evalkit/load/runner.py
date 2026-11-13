"""Asynchronous load generator for concurrent ASR streaming and LLM inference."""

import asyncio
import json
import math
import struct
import time
from typing import Any, Dict, List, Optional
import httpx
import websockets


def percentile(values: List[float], p: float) -> float:
    """Compute p-th percentile of a list of floats (0 <= p <= 100)."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    d0 = sorted_vals[int(f)] * (c - k)
    d1 = sorted_vals[int(c)] * (k - f)
    return d0 + d1


def generate_pcm_chunk(duration_sec: float = 0.2, sample_rate: int = 16000) -> bytes:
    """Generate 16-bit mono PCM audio chunk."""
    n_samples = int(sample_rate * duration_sec)
    return struct.pack(f"<{n_samples}h", *(0 for _ in range(n_samples)))


async def simulate_call(
    call_id: int,
    speech_ws_url: str,
    llm_url: str,
    call_duration_sec: float,
    llm_interval_sec: float,
    transcript_latencies: List[float],
    llm_latencies: List[float],
    api_key: Optional[str] = None,
):
    """Simulate one active telephone call: stream audio in real time and trigger periodic LLM requests."""
    chunk_sec = 0.2
    pcm_chunk = generate_pcm_chunk(duration_sec=chunk_sec)

    llm_endpoint = f"{llm_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async def run_audio_stream():
        try:
            async with websockets.connect(speech_ws_url) as ws:
                start_time = time.perf_counter()
                total_chunks = int(call_duration_sec / chunk_sec)

                async def receiver():
                    try:
                        async for message in ws:
                            recv_time = time.perf_counter()
                            try:
                                data = json.loads(message)
                                # Audio end timestamp or line receipt time
                                if data.get("type") == "transcript":
                                    audio_end = float(data.get("end", 0.0))
                                    elapsed = recv_time - start_time
                                    delay = max(0.01, elapsed - audio_end)
                                    transcript_latencies.append(delay)
                            except Exception:
                                pass
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass

                recv_task = asyncio.create_task(receiver())

                for chunk_idx in range(total_chunks):
                    await ws.send(pcm_chunk)
                    await asyncio.sleep(chunk_sec)

                # Wait small grace period for final transcripts
                await asyncio.sleep(0.5)
                recv_task.cancel()
        except Exception:
            # Service unreachable or closed
            pass

    async def run_llm_queries():
        async with httpx.AsyncClient(timeout=30.0) as client:
            elapsed = 0.0
            query_idx = 1
            while elapsed < call_duration_sec:
                await asyncio.sleep(llm_interval_sec)
                elapsed += llm_interval_sec

                prompt = f"Call {call_id} query {query_idx}: Identify customer sentiment and complaints."
                payload = {
                    "model": "service-model",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                }
                t0 = time.perf_counter()
                try:
                    resp = await client.post(llm_endpoint, headers=headers, json=payload)
                    if resp.status_code == 200:
                        lat = time.perf_counter() - t0
                        llm_latencies.append(lat)
                except Exception:
                    pass
                query_idx += 1

    await asyncio.gather(run_audio_stream(), run_llm_queries())


async def run_load_test(
    speech_url: str,
    llm_url: str,
    num_calls: int = 10,
    call_duration_sec: float = 10.0,
    llm_interval_sec: float = 3.0,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Run concurrent load test simulating N calls."""
    # Convert http:// or https:// to ws:// or wss://
    ws_url = speech_url.replace("http://", "ws://").replace("https://", "wss://").rstrip("/")
    if not ws_url.endswith("/v1/stream?sample_rate=16000"):
        ws_url = f"{ws_url}/v1/stream?sample_rate=16000"

    transcript_latencies: List[float] = []
    llm_latencies: List[float] = []

    start_time = time.perf_counter()
    tasks = [
        simulate_call(
            call_id=i + 1,
            speech_ws_url=ws_url,
            llm_url=llm_url,
            call_duration_sec=call_duration_sec,
            llm_interval_sec=llm_interval_sec,
            transcript_latencies=transcript_latencies,
            llm_latencies=llm_latencies,
            api_key=api_key,
        )
        for i in range(num_calls)
    ]
    await asyncio.gather(*tasks)
    total_test_duration = time.perf_counter() - start_time

    return {
        "num_calls": num_calls,
        "test_duration_sec": total_test_duration,
        "transcripts": {
            "total_lines_received": len(transcript_latencies),
            "p50_latency_sec": percentile(transcript_latencies, 50.0),
            "p95_latency_sec": percentile(transcript_latencies, 95.0),
            "raw_latencies": transcript_latencies,
        },
        "llm": {
            "total_answers_received": len(llm_latencies),
            "p50_latency_sec": percentile(llm_latencies, 50.0),
            "p95_latency_sec": percentile(llm_latencies, 95.0),
            "raw_latencies": llm_latencies,
        },
    }

