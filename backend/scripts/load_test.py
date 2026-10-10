"""Load test: many phone calls at once, at no cost.

Starts its own copy of the backend with stand-ins for the speech recogniser
and the AI (each just waits a set time and answers), in-memory storage, and
nothing from .env: no real service is called, no real database is touched,
and nothing is sent to anyone. Then it plays that many two-sided calls into
it at once, as Plivo would (separate caller and executive tracks, 16 kHz,
real time), and reports whether the backend kept up.

From backend/:

    python -m scripts.load_test --calls 50 --seconds 60

What it shows is this machine's limit with one backend process, and where
the backend falls behind first. It does not show what the real speech
recogniser, LLM or PostgreSQL add: their speed is set by --asr-seconds and
--llm-seconds, and storage is in memory.

What is measured:

    calls completed          every call must end and be marked completed
    speech transcribed       stretches of speech that became transcript lines
    finishing time           from hang-up until the call is completed
    first analysis           from the call's start until its first complaint
                             shows (speech, then the AI analysis)
    Live Calls page          how long the supervisor's live view takes to load
    sender lag               how far this script fell behind real time: when
                             that is large, the machine could not even
                             produce the calls, and the result says little
                             about the backend
"""

import argparse
import asyncio
import base64
import json
import math
import os
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field


def _use_stand_in_settings() -> None:
    """Nothing from the developer's .env: no real keys, database or SMS
    gateway. Called before any app module is imported, in the script's own
    process and (inherited) in the backend it starts."""
    os.environ["APP_ENV_FILE"] = ""
    os.environ["AUTH_SECRET_KEY"] = "load-test-only-secret-key-0123456789abcdef"
    os.environ["DIARIZATION_PROVIDER"] = "scripted"
    os.environ["LOG_LEVEL"] = "WARNING"


LOAD_USER_ID = "load-test-supervisor"
SAMPLE_RATE = 16000
# Each side speaks for 3 s of every 8 s, in turn: caller, pause, executive, pause.
CYCLE_SECONDS = 8.0
SPEECH_SECONDS = 3.0
TRACK_OFFSETS = {"inbound": 0.0, "outbound": 4.0}
SEGMENT_WORD = "segment"
# The first complaint of a call should show within this long of its start.
MAX_FIRST_ANALYSIS_SECONDS = 30.0


# ---- The stand-in backend ----


def serve(port: int, asr_seconds: float, llm_seconds: float) -> None:
    import uvicorn

    import app.api.wiring as wiring
    from app.ai.asr.provider import ASRProvider, ASRResult
    from app.ai.complaint.provider import ComplaintDetectionProvider, ComplaintDetectionResult
    from app.ai.language.provider import (
        LanguageIdentificationProvider,
        LanguageIdentificationResult,
        LanguageSpan,
    )
    from app.ai.question.provider import QuestionSuggestionProvider
    from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentResult
    from app.api.app_factory import create_app
    from app.core.config import get_settings
    from app.domain.sentiment import SentimentLabel
    from app.domain.user import User, UserRole

    class StandInASR(ASRProvider):
        def __init__(self) -> None:
            self._count = 0
            self._lock = threading.Lock()

        def transcribe(self, audio: bytes, language_hint: str | None = None) -> ASRResult:
            time.sleep(asr_seconds)
            with self._lock:
                self._count += 1
                number = self._count
            return ASRResult(
                transcript=f"{SEGMENT_WORD} {number} the bill was higher than I was told",
                detected_language="en",
                start_time=0.0,
                end_time=len(audio) / (2 * SAMPLE_RATE),
            )

    class StandInLanguage(LanguageIdentificationProvider):
        def identify(self, text: str) -> LanguageIdentificationResult:
            return LanguageIdentificationResult([LanguageSpan("en", 0.99)])

    class StandInComplaints(ComplaintDetectionProvider):
        def detect(self, conversation, learning_context=()):
            time.sleep(llm_seconds)
            return [ComplaintDetectionResult("Cost", 0.9, "The bill was higher.")]

    class StandInSentiment(SentimentAnalysisProvider):
        def analyze(self, conversation, learning_context=()):
            time.sleep(llm_seconds)
            return SentimentResult(SentimentLabel.NEGATIVE, 0.8, "The bill was higher.")

    class StandInQuestions(QuestionSuggestionProvider):
        def generate(self, context):
            time.sleep(llm_seconds)
            return None

    wiring.create_asr_provider = lambda settings: StandInASR()
    wiring.create_language_provider = lambda settings: StandInLanguage()
    services = wiring.build_api_services(
        StandInComplaints(), StandInSentiment(), StandInQuestions(), get_settings()
    )
    services.user_repository.save(
        User(LOAD_USER_ID, "load-test@example.com", "hash", UserRole.SUPERVISOR, True, time.time())
    )
    uvicorn.run(create_app(services), host="127.0.0.1", port=port, log_level="warning")


# ---- The calls ----


@dataclass
class CallOutcome:
    started: bool = False
    completed: bool = False
    error: str | None = None
    # Stretches of speech sent, and how many became transcript.
    expected_segments: int = 0
    transcribed_segments: int = 0
    finish_seconds: float | None = None
    # Whether this call's first analysis was followed, and when it showed.
    watched: bool = False
    first_analysis_seconds: float | None = None
    sender_lag_seconds: float = 0.0


@dataclass
class Results:
    calls: list[CallOutcome] = field(default_factory=list)
    live_view_seconds: list[float] = field(default_factory=list)
    live_view_errors: int = 0


def _frames(frame_seconds: float) -> tuple[str, str]:
    """One frame of speech-like sound and one of silence, base64 as sent."""
    samples = int(SAMPLE_RATE * frame_seconds)
    tone = b"".join(
        int(8000 * math.sin(2 * math.pi * 220 * n / SAMPLE_RATE)).to_bytes(2, "little", signed=True)
        for n in range(samples)
    )
    return base64.b64encode(tone).decode(), base64.b64encode(b"\x00\x00" * samples).decode()


def _speaking(track: str, at: float) -> bool:
    return (at - TRACK_OFFSETS[track]) % CYCLE_SECONDS < SPEECH_SECONDS


def expected_segments(seconds: float) -> int:
    """Stretches of speech that start within a call of this length."""
    return sum(
        1
        for track, offset in TRACK_OFFSETS.items()
        for start in _starts(offset, seconds)
        if start + SPEECH_SECONDS <= seconds
    )


def _starts(offset: float, seconds: float):
    start = offset
    while start < seconds:
        yield start
        start += CYCLE_SECONDS


async def _one_call(
    http, base: str, seconds: float, frame_seconds: float, frames: tuple[str, str], watch: bool
) -> CallOutcome:
    import websockets

    outcome = CallOutcome(expected_segments=expected_segments(seconds), watched=watch)
    speech, silence = frames
    try:
        started = (await http.post("/api/v1/test-calls", json={"from_number": ""})).json()
        call_id = started["call_id"]
        outcome.started = True
        began = time.monotonic()
        watcher = (
            asyncio.create_task(_first_analysis(http, call_id, began, seconds + 120))
            if watch
            else None
        )

        url = base.replace("http", "ws", 1) + started["stream_path"]
        async with websockets.connect(url, max_size=None) as socket:
            await socket.send(
                json.dumps(
                    {
                        "event": "start",
                        "start": {
                            "mediaFormat": {"encoding": "audio/x-l16", "sampleRate": SAMPLE_RATE},
                            "tracks": list(TRACK_OFFSETS),
                        },
                    }
                )
            )
            for chunk in range(int(seconds / frame_seconds)):
                at = chunk * frame_seconds
                for track in TRACK_OFFSETS:
                    payload = speech if _speaking(track, at) else silence
                    await socket.send(
                        '{"event":"media","media":{"track":"%s","chunk":%d,"payload":"%s"}}'
                        % (track, chunk, payload)
                    )
                # Real time, as a phone call sends it.
                delay = began + at + frame_seconds - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    outcome.sender_lag_seconds = max(outcome.sender_lag_seconds, -delay)
            await socket.send('{"event":"stop"}')

        hung_up = time.monotonic()
        await http.post(
            f"/api/v1/test-calls/{started['provider_call_id']}/end",
            json={"duration_seconds": seconds},
            timeout=120,
        )
        deadline = hung_up + 180
        while time.monotonic() < deadline:
            call = (await http.get(f"/api/v1/calls/{call_id}")).json()
            if call.get("status") == "completed":
                outcome.completed = True
                outcome.finish_seconds = time.monotonic() - hung_up
                outcome.transcribed_segments = sum(
                    u["transcript"].count(SEGMENT_WORD) for u in call["utterances"]
                )
                break
            await asyncio.sleep(1.0)
        if watcher is not None:
            outcome.first_analysis_seconds = await watcher
    except Exception as error:  # one call's failure is a result, not the end of the test
        outcome.error = f"{type(error).__name__}: {error}"[:200]
    return outcome


async def _first_analysis(http, call_id: str, began: float, give_up_after: float) -> float | None:
    """Seconds from the call's start until its first complaint shows."""
    while time.monotonic() - began < give_up_after:
        try:
            analysis = (await http.get(f"/api/v1/calls/{call_id}/analysis")).json()
            if analysis.get("coverage", {}).get("complaints"):
                return time.monotonic() - began
        except Exception:
            pass
        await asyncio.sleep(1.0)
    return None


async def _watch_live_view(http, results: Results, stop: asyncio.Event) -> None:
    while not stop.is_set():
        began = time.monotonic()
        try:
            response = await http.get("/api/v1/live-calls", timeout=60)
            response.raise_for_status()
            results.live_view_seconds.append(time.monotonic() - began)
        except Exception:
            results.live_view_errors += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass


async def run_calls(
    base: str, calls: int, seconds: float, ramp_seconds: float, frame_seconds: float
) -> Results:
    import httpx

    from app.domain.user import User, UserRole
    from app.security.jwt import create_access_token

    token = create_access_token(
        User(LOAD_USER_ID, "load-test@example.com", "hash", UserRole.SUPERVISOR, True, time.time())
    )
    results = Results()
    frames = _frames(frame_seconds)
    # First analysis is followed on a sample of the calls only.
    watched = set(range(0, calls, max(1, calls // 10)))
    limits = httpx.Limits(max_connections=calls + 50)
    async with httpx.AsyncClient(
        base_url=base, headers={"Authorization": f"Bearer {token}"}, timeout=30, limits=limits
    ) as http:
        stop = asyncio.Event()
        live_view = asyncio.create_task(_watch_live_view(http, results, stop))

        async def delayed(index: int) -> CallOutcome:
            await asyncio.sleep(ramp_seconds * index / max(1, calls))
            return await _one_call(http, base, seconds, frame_seconds, frames, index in watched)

        results.calls = list(await asyncio.gather(*(delayed(i) for i in range(calls))))
        stop.set()
        await live_view
    return results


# ---- The report ----


def _spread(values: list[float]) -> str:
    if not values:
        return "no data"
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]
    return f"median {statistics.median(ordered):.1f} s, 95% within {p95:.1f} s, worst {ordered[-1]:.1f} s"


def summarize(results: Results, calls: int, seconds: float) -> tuple[str, bool]:
    """The report, and whether the backend kept up."""
    outcomes = results.calls
    completed = [o for o in outcomes if o.completed]
    failed = [o for o in outcomes if o.error]
    expected = sum(o.expected_segments for o in completed)
    transcribed = sum(o.transcribed_segments for o in completed)
    all_heard = sum(
        1 for o in completed if o.transcribed_segments >= math.ceil(0.9 * o.expected_segments)
    )
    finishing = [o.finish_seconds for o in completed if o.finish_seconds is not None]
    watched = [o for o in outcomes if o.first_analysis_seconds is not None]
    sender_lag = max((o.sender_lag_seconds for o in outcomes), default=0.0)
    # A call's first complaint should show well before a call of this
    # length ends: otherwise the AI analysis is not keeping up with speech.
    analysed_in_time = all(
        o.first_analysis_seconds is not None
        and o.first_analysis_seconds <= max(MAX_FIRST_ANALYSIS_SECONDS, 0.0)
        for o in outcomes
        if o.watched
    )
    kept_up = (
        len(completed) == calls
        and not failed
        and all_heard == calls
        and (not finishing or max(finishing) <= 30.0)
        and results.live_view_errors == 0
        and (analysed_in_time or seconds < MAX_FIRST_ANALYSIS_SECONDS)
    )
    lines = [
        f"{calls} calls at once, {seconds:.0f} s each",
        f"  calls completed        {len(completed)} of {calls}",
        f"  calls that failed      {len(failed)}"
        + (f"  (first: {failed[0].error})" if failed else ""),
        f"  speech transcribed     {transcribed} of {expected} stretches"
        f"; {all_heard} of {calls} calls had (nearly) all of theirs",
        f"  finishing time         {_spread(finishing)}",
        f"  first analysis         {_spread([o.first_analysis_seconds for o in watched])}"
        f"  ({len(watched)} of {sum(1 for o in outcomes if o.watched)} followed calls got one)",
        f"  Live Calls page        {_spread(results.live_view_seconds)}"
        f"; {results.live_view_errors} failed loads",
        f"  sender lag             worst {sender_lag:.1f} s"
        + ("  (the test machine itself could not keep real time)" if sender_lag > 2 else ""),
        f"  verdict                {'kept up' if kept_up else 'DID NOT keep up'}",
    ]
    return "\n".join(lines), kept_up


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--calls", type=int, default=20, help="calls at once")
    parser.add_argument("--seconds", type=float, default=60.0, help="length of each call")
    parser.add_argument("--ramp-seconds", type=float, default=5.0, help="calls start over this long")
    parser.add_argument("--frame-ms", type=int, default=20, help="audio frame length (Plivo: 20)")
    parser.add_argument("--asr-seconds", type=float, default=0.4, help="stand-in speech recogniser")
    parser.add_argument("--llm-seconds", type=float, default=1.0, help="stand-in AI, per request")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    _use_stand_in_settings()

    if args.serve:
        serve(args.port, args.asr_seconds, args.llm_seconds)
        return 0

    base = f"http://127.0.0.1:{args.port}"
    server = subprocess.Popen(
        [
            sys.executable, "-m", "scripts.load_test", "--serve",
            "--port", str(args.port),
            "--asr-seconds", str(args.asr_seconds),
            "--llm-seconds", str(args.llm_seconds),
        ]
    )
    try:
        _wait_until_up(base, server)
        results = asyncio.run(
            run_calls(base, args.calls, args.seconds, args.ramp_seconds, args.frame_ms / 1000)
        )
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
    text, kept_up = summarize(results, args.calls, args.seconds)
    print(text)
    return 0 if kept_up else 2


def _wait_until_up(base: str, server: subprocess.Popen) -> None:
    import httpx

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise SystemExit("The stand-in backend stopped while starting.")
        try:
            if httpx.get(f"{base}/health/live", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1.0)
    raise SystemExit("The stand-in backend did not start within 3 minutes.")


if __name__ == "__main__":
    sys.exit(main())
