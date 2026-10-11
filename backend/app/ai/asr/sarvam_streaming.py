"""Sarvam's streaming speech recogniser, for live calls.

The ordinary recogniser (sarvam_provider) is sent a finished piece of audio
and answers with its text, so a line can only appear a second or more after
it was spoken. Here one connection stays open for a call's audio stream:
the audio is sent as it arrives, Sarvam notices where someone starts and
stops speaking, and the text of each stretch of speech comes back a
fraction of a second after it ends.

One SarvamStreamingSession per audio stream (per track when a call's two
sides arrive separately). It runs on the event loop that serves the call's
media stream. What comes out are StreamedSegments: the words, where in the
stream they were said, and that stretch of audio (the caller of a mixed
stream still has to tell the speakers apart from it).

Times are worked out here from how much audio had been sent when Sarvam
reported speech starting and stopping, less what its detector is known to
lag by; they are good to a few tenths of a second.

If the connection cannot be made or drops, the session says so once
(on_failure) and stops; the caller falls back to the ordinary recogniser.
"""

import asyncio
import base64
import json
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from app.core.constants import SUPPORTED_LANGUAGES

logger = logging.getLogger(__name__)

# Sarvam's detector works in frames of 512 samples.
_FRAME_SAMPLES = 512
# It reports speech this many frames after it began (its own defaults:
# 9 frames kept from before the speech plus 2 to be sure of it).
_START_LAG_FRAMES = 11
# Audio goes out in pieces of about this long.
_SEND_SECONDS = 0.1
# How much audio from before the current stretch of speech is kept.
_KEEP_SECONDS = 1.0
# While nobody speaks, this much of the latest audio is kept: Sarvam
# reports speech a little after it began.
_QUIET_KEEP_SECONDS = 3.0
# At the end of the stream, with nobody known to be speaking, how long to
# wait in case Sarvam was about to report speech.
_LAST_WORD_SECONDS = 0.3
SUPPORTED_SAMPLE_RATES = (8000, 16000)


class StreamingConnection(Protocol):
    """What the session needs of a WebSocket: send text, receive text
    (iterating ends when the connection closes), close."""

    async def send(self, message: str) -> None: ...

    def __aiter__(self): ...

    async def close(self) -> None: ...


Connect = Callable[[str, dict[str, str]], Awaitable[StreamingConnection]]


async def connect_websocket(url: str, headers: dict[str, str]) -> StreamingConnection:
    import websockets

    return await websockets.connect(url, additional_headers=headers, open_timeout=10)


@dataclass(frozen=True)
class StreamedSegment:
    """One stretch of speech, transcribed."""

    transcript: str
    # Seconds from the start of this audio stream.
    start_time: float
    end_time: float
    # That stretch of the stream: 16-bit mono PCM at the stream's rate.
    audio: bytes
    # The language Sarvam heard ("ta"), when it is one this system supports.
    language: str | None = None
    # The stretch was ended by its length, not by a pause: the speaker
    # carries on in the next one, which continues this.
    cut_short: bool = False
    continues_previous: bool = False


@dataclass(frozen=True)
class StreamingSettings:
    api_key: str
    url: str
    model: str
    mode: str | None
    # Sarvam ends a stretch of speech after about this many silent frames
    # (32 ms each at 16 kHz): 8 is a pause of a quarter of a second.
    pause_frames: int = 8
    # A stretch still going after this long is cut, so a long sentence
    # shows on screen in parts instead of all at the end.
    max_segment_seconds: float = 8.0

    @staticmethod
    def from_settings(settings) -> "StreamingSettings":
        base = settings.sarvam_base_url.rstrip("/")
        socket = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        return StreamingSettings(
            api_key=settings.sarvam_api_key,
            url=f"{socket}/speech-to-text/ws",
            model=settings.sarvam_stt_model,
            mode=settings.sarvam_stt_mode,
            pause_frames=settings.asr_streaming_pause_frames,
            max_segment_seconds=settings.asr_streaming_max_segment_seconds,
        )


StreamingFactory = Callable[
    [int, Callable[[StreamedSegment], None], Callable[[str], None]], "SarvamStreamingSession"
]


def build_streaming_asr(settings) -> StreamingFactory | None:
    """What opens a streaming session for a live audio stream, when
    LIVE_ASR_MODE=streaming and Sarvam is the recogniser; else None."""
    if settings.live_asr_mode.strip().lower() != "streaming":
        return None
    key = (settings.sarvam_api_key or "").strip()
    if settings.asr_provider.strip().lower() != "sarvam" or key in ("", "not_configured"):
        logger.warning(
            "LIVE_ASR_MODE=streaming needs ASR_PROVIDER=sarvam and its key; "
            "live speech is recognised in chunks instead."
        )
        return None
    streaming = StreamingSettings.from_settings(settings)
    return lambda sample_rate, on_segment, on_failure: SarvamStreamingSession(
        streaming, sample_rate, on_segment, on_failure
    )


async def _close_quietly(connection: StreamingConnection) -> None:
    try:
        await connection.close()
    except Exception:
        pass


def _language(code: Any) -> str | None:
    if not isinstance(code, str):
        return None
    language = code.strip().split("-")[0].lower()
    return language if language in SUPPORTED_LANGUAGES else None


class SarvamStreamingSession:
    def __init__(
        self,
        settings: StreamingSettings,
        sample_rate: int,
        on_segment: Callable[[StreamedSegment], None],
        on_failure: Callable[[str], None],
        connect: Connect = connect_websocket,
    ) -> None:
        if sample_rate not in SUPPORTED_SAMPLE_RATES:
            raise ValueError(f"Sarvam streams at 8 or 16 kHz, not {sample_rate} Hz.")
        self._settings = settings
        self._rate = sample_rate
        self._on_segment = on_segment
        self._on_failure = on_failure
        self._connect = connect
        self._connection: StreamingConnection | None = None
        self._outgoing: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []
        self._failed = False
        self._closing = False
        # The end of the stream has been told to Sarvam.
        self._ending = False
        # The stream's audio from _kept_from (a sample number) onwards.
        self._kept = bytearray()
        self._kept_from = 0
        self._fed_samples = 0
        self._sent_samples = 0
        # Where the stretch of speech now going on began; None between them.
        self._open_since: float | None = None
        self._flush_sent = False
        # Stretches that have ended and whose text is still to come.
        self._ended: deque[tuple[float, float, bool, bool]] = deque()
        self._last_end = 0.0
        # Everything before this has been transcribed and handed over.
        self._heard_until = 0.0
        self._continues = False
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def alive(self) -> bool:
        return not self._failed and not self._closing

    @property
    def frame_seconds(self) -> float:
        return _FRAME_SAMPLES / self._rate

    def url(self) -> str:
        query = {
            # Sarvam works the language out itself, stretch by stretch.
            "language-code": "unknown",
            "model": self._settings.model,
            "sample_rate": self._rate,
            "input_audio_codec": "pcm_s16le",
            "vad_signals": "true",
            "flush_signal": "true",
            "negative_frames_count": self._settings.pause_frames,
            "negative_frames_window": self._settings.pause_frames + 2,
        }
        if self._settings.mode:
            query["mode"] = self._settings.mode
        return f"{self._settings.url}?{urlencode(query)}"

    def start(self) -> None:
        """Connect in the background. Audio fed meanwhile waits its turn."""
        self._tasks.append(asyncio.create_task(self._run()))

    def feed(self, pcm: bytes) -> None:
        """Take more of the stream's audio (16-bit mono PCM)."""
        if not pcm or not self.alive:
            return
        self._kept.extend(pcm)
        self._fed_samples += len(pcm) // 2
        self._outgoing.put_nowait(pcm)

    @property
    def heard_until(self) -> float:
        """Where in the stream (seconds) unheard_audio() begins."""
        return max(self._heard_until, self._kept_from / self._rate)

    def unheard_audio(self) -> bytes:
        """The audio since the last stretch whose text was handed over:
        what a fallback recogniser still has to hear after a failure."""
        start = max(0, int(self.heard_until * self._rate) - self._kept_from) * 2
        return bytes(self._kept[start:])

    async def finish(self, timeout: float = 3.0) -> None:
        """No more audio: have what is still being spoken transcribed,
        wait for it (at most timeout seconds), and close."""
        if self._failed or self._closing:
            await self._close()
            return
        self._closing = True
        self._idle.clear()
        self._outgoing.put_nowait(None)
        try:
            await asyncio.wait_for(self._idle.wait(), timeout)
        except asyncio.TimeoutError:
            # What it had not answered for goes to the fallback.
            self._fail(f"it did not finish in {timeout:.0f}s")
        await self._close()

    async def _close(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []
        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception:
                pass
            self._connection = None

    async def _run(self) -> None:
        try:
            self._connection = await self._connect(
                self.url(), {"Api-Subscription-Key": self._settings.api_key}
            )
        except Exception as exc:
            self._fail(f"could not connect ({type(exc).__name__})")
            return
        sender = asyncio.create_task(self._send())
        self._tasks.append(sender)
        try:
            async for raw in self._connection:
                self._receive(raw)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(f"the connection broke ({type(exc).__name__})")
            return
        if not self._closing:
            self._fail("the connection closed")

    def _fail(self, reason: str) -> None:
        if self._failed:
            return
        self._failed = True
        self._idle.set()
        logger.warning("Streaming speech recognition stopped: %s", reason)
        try:
            self._on_failure(reason)
        except Exception:
            logger.exception("Could not hand over after the streaming recogniser failed")
        self._release()

    def _release(self) -> None:
        """After a failure nobody calls finish(): stop sending and let the
        connection go."""
        current = asyncio.current_task()
        for task in self._tasks:
            if task is not current:
                task.cancel()
        connection, self._connection = self._connection, None
        if connection is not None:
            self._closer = asyncio.create_task(_close_quietly(connection))

    async def _send(self) -> None:
        piece = int(self._rate * _SEND_SECONDS) * 2
        pending = bytearray()
        finished = False
        while not finished:
            item = await self._outgoing.get()
            if item is None:
                finished = True
            else:
                pending.extend(item)
            while len(pending) >= piece or (finished and pending):
                await self._send_audio(bytes(pending[:piece]))
                del pending[:piece]
            await self._cut_if_long()
        # The end of the stream: whatever is still being spoken is final.
        await self._connection.send(json.dumps({"type": "flush"}))
        self._ending = True
        if not self._answers_due():
            await asyncio.sleep(_LAST_WORD_SECONDS)
        if not self._answers_due():
            self._idle.set()

    def _answers_due(self) -> bool:
        return self._open_since is not None or bool(self._ended)

    async def _send_audio(self, pcm: bytes) -> None:
        await self._connection.send(
            json.dumps(
                {
                    "audio": {
                        "data": base64.b64encode(pcm).decode("ascii"),
                        "sample_rate": str(self._rate),
                        "encoding": "audio/wav",
                    }
                }
            )
        )
        self._sent_samples += len(pcm) // 2
        if self._open_since is None and not self._ended:
            # Nobody is speaking: the silence need not be kept.
            quiet_until = self._position() - _QUIET_KEEP_SECONDS
            if quiet_until > self._heard_until:
                self._heard_until = quiet_until
                self._forget_before(quiet_until)

    async def _cut_if_long(self) -> None:
        if (
            self._open_since is not None
            and not self._flush_sent
            and self._position() - self._open_since >= self._settings.max_segment_seconds
        ):
            self._flush_sent = True
            await self._connection.send(json.dumps({"type": "flush"}))

    def _position(self) -> float:
        """How much of the stream has been sent, in seconds."""
        return self._sent_samples / self._rate

    def _receive(self, raw: Any) -> None:
        try:
            message = json.loads(raw)
        except (TypeError, ValueError):
            return
        if not isinstance(message, dict):
            return
        kind, data = message.get("type"), message.get("data")
        data = data if isinstance(data, dict) else {}
        if kind == "events":
            signal = data.get("signal_type")
            if signal == "START_SPEECH":
                self._speech_started()
            elif signal == "END_SPEECH":
                self._speech_ended()
        elif kind == "data":
            self._transcribed(data)
        elif kind == "error":
            self._fail(f"Sarvam reported an error: {str(data or message)[:200]}")

    def _speech_started(self) -> None:
        began = self._position() - _START_LAG_FRAMES * self.frame_seconds
        self._open_since = max(self._last_end, began, 0.0)

    def _speech_ended(self) -> None:
        # At the end of the stream the last stretch is cut too, but nothing
        # follows it.
        cut = self._flush_sent and not self._closing
        # A pause is noticed only once it has lasted; a cut is immediate.
        immediate = self._flush_sent or self._closing
        lag = 0.0 if immediate else self._settings.pause_frames * self.frame_seconds
        start = self._open_since if self._open_since is not None else self._last_end
        end = max(start, self._position() - lag)
        self._ended.append((start, end, cut, self._continues))
        self._last_end = end
        self._continues = cut
        self._open_since = None
        self._flush_sent = False

    def _transcribed(self, data: dict) -> None:
        if self._ended:
            start, end, cut, continues = self._ended.popleft()
        else:
            # Text with no "speech ended" before it: take the audio since
            # the last stretch (Sarvam says how long it was).
            end = self._position()
            duration = (data.get("metrics") or {}).get("audio_duration")
            start = self._open_since if self._open_since is not None else self._last_end
            if isinstance(duration, (int, float)) and duration > 0:
                start = max(start, end - float(duration))
            cut, continues = self._flush_sent, self._continues
            self._last_end, self._continues = end, cut
            self._open_since, self._flush_sent = None, False
        self._heard_until = max(self._heard_until, end)
        transcript = data.get("transcript")
        if isinstance(transcript, str) and transcript.strip() and end > start:
            segment = StreamedSegment(
                transcript=transcript.strip(),
                start_time=start,
                end_time=end,
                audio=self._audio(start, end),
                language=_language(data.get("language_code")),
                cut_short=cut,
                continues_previous=continues,
            )
            try:
                self._on_segment(segment)
            except Exception:
                logger.exception("Could not take a transcribed stretch of speech")
        self._forget_before(end - _KEEP_SECONDS)
        if self._ending and not self._answers_due():
            self._idle.set()

    def _audio(self, start: float, end: float) -> bytes:
        first = max(0, int(start * self._rate) - self._kept_from) * 2
        last = max(0, int(end * self._rate) - self._kept_from) * 2
        return bytes(self._kept[first:last])

    def _forget_before(self, seconds: float) -> None:
        drop = int(max(0.0, seconds) * self._rate) - self._kept_from
        if drop > 0:
            del self._kept[: drop * 2]
            self._kept_from += drop
