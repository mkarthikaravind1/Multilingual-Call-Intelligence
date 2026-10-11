"""The streaming speech recogniser (LIVE_ASR_MODE=streaming): the call's
audio goes to Sarvam over one open connection as it arrives, each stretch of
speech comes back as a line, and a call whose connection fails carries on
with the ordinary (chunked) recogniser without losing audio.

Sarvam is played here by a scripted connection: nothing leaves the machine.
"""

import asyncio
import audioop
import base64
import json
import math
import struct
from urllib.parse import parse_qs, urlparse

import pytest

from app.ai.asr.sarvam_streaming import (
    SarvamStreamingSession,
    StreamedSegment,
    StreamingSettings,
    build_streaming_asr,
)
from app.core.config import Settings
from tests.test_telephony import (
    _answer_call,
    _build_client,
    _FakeASRProvider,
    _FakeLanguageProvider,
    _stream_path,
    _wait_for_stream,
)

RATE = 16000
SETTINGS = StreamingSettings(
    api_key="test-key",
    url="wss://sarvam.test/speech-to-text/ws",
    model="saaras:v3",
    mode="codemix",
    pause_frames=8,
    max_segment_seconds=8.0,
)


def _speech(seconds: float, rate: int = RATE) -> bytes:
    count = int(rate * seconds)
    return b"".join(
        struct.pack("<h", int(12000 * math.sin(2 * math.pi * 300 * n / rate))) for n in range(count)
    )


def _silence(seconds: float, rate: int = RATE) -> bytes:
    return b"\x00\x00" * int(rate * seconds)


class ScriptedSarvam:
    """Stands in for Sarvam's connection. It answers the way the real one
    was seen to: "speech started" a little after loud audio begins, "speech
    ended" and the text once it has been quiet for the pause, and both at
    once on a flush."""

    def __init__(self, language: str = "ta-IN", texts=None, break_after: float | None = None):
        self.url = ""
        self.headers: dict[str, str] = {}
        self.sent: list[dict] = []
        self.closed = False
        self._incoming: asyncio.Queue = asyncio.Queue()
        self._language = language
        self._texts = list(texts) if texts is not None else None
        self._break_after = break_after
        self._heard = 0.0
        self._speaking = False
        self._quiet = 0.0
        self._lines = 0

    async def connect(self, url: str, headers: dict[str, str]) -> "ScriptedSarvam":
        self.url, self.headers = url, headers
        return self

    async def send(self, message: str) -> None:
        payload = json.loads(message)
        self.sent.append(payload)
        if payload.get("type") == "flush":
            if self._speaking:
                self._end()
            return
        pcm = base64.b64decode(payload["audio"]["data"])
        seconds = len(pcm) / 2 / RATE
        self._heard += seconds
        if audioop.rms(pcm, 2) > 500:
            self._quiet = 0.0
            if not self._speaking:
                self._speaking = True
                self._push({"type": "events", "data": {"signal_type": "START_SPEECH"}})
        elif self._speaking:
            self._quiet += seconds
            if self._quiet >= 0.25:
                self._end()
        if self._break_after is not None and self._heard >= self._break_after:
            self._incoming.put_nowait(ConnectionError("dropped"))

    def _end(self) -> None:
        self._speaking, self._quiet = False, 0.0
        self._lines += 1
        text = self._texts.pop(0) if self._texts else f"line {self._lines}"
        self._push({"type": "events", "data": {"signal_type": "END_SPEECH"}})
        self._push(
            {
                "type": "data",
                "data": {"transcript": text, "language_code": self._language, "metrics": {}},
            }
        )

    def _push(self, message: dict) -> None:
        self._incoming.put_nowait(json.dumps(message))

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        item = await self._incoming.get()
        if isinstance(item, Exception):
            raise item
        if item is None:
            raise StopAsyncIteration
        return item

    async def close(self) -> None:
        self.closed = True
        self._incoming.put_nowait(None)

    @property
    def flushes(self) -> int:
        return sum(1 for message in self.sent if message.get("type") == "flush")


def _run(audio: bytes, sarvam=None, settings: StreamingSettings = SETTINGS, connect=None):
    """Feed the audio through a session in 20 ms frames, finish, and return
    (segments, failures, session, sarvam)."""
    sarvam = sarvam or ScriptedSarvam()
    segments: list[StreamedSegment] = []
    failures: list[str] = []

    async def go() -> SarvamStreamingSession:
        session = SarvamStreamingSession(
            settings, RATE, segments.append, failures.append, connect or sarvam.connect
        )
        session.start()
        frame = RATE // 50 * 2
        for start in range(0, len(audio), frame):
            session.feed(audio[start : start + frame])
            if start % (frame * 10) == 0:
                await asyncio.sleep(0)
        await asyncio.sleep(0.01)
        await session.finish(timeout=1.0)
        return session

    return segments, failures, asyncio.run(go()), sarvam


def test_the_connection_asks_for_what_the_settings_say():
    _, _, _, sarvam = _run(_speech(0.5))

    query = {key: values[0] for key, values in parse_qs(urlparse(sarvam.url).query).items()}
    assert sarvam.url.startswith("wss://sarvam.test/speech-to-text/ws?")
    assert sarvam.headers == {"Api-Subscription-Key": "test-key"}
    assert query == {
        "language-code": "unknown",
        "model": "saaras:v3",
        "mode": "codemix",
        "sample_rate": "16000",
        "input_audio_codec": "pcm_s16le",
        "vad_signals": "true",
        "flush_signal": "true",
        "negative_frames_count": "8",
        "negative_frames_window": "10",
    }


def test_each_stretch_of_speech_comes_back_as_a_line_with_its_time_and_audio():
    audio = _silence(1.0) + _speech(2.0) + _silence(1.0) + _speech(1.5) + _silence(1.0)

    segments, failures, _, _ = _run(audio, ScriptedSarvam(texts=["vanakkam", "sollunga"]))

    assert failures == []
    assert [segment.transcript for segment in segments] == ["vanakkam", "sollunga"]
    first, second = segments
    assert (first.language, first.cut_short, first.continues_previous) == ("ta", False, False)
    # Good to a few tenths of a second, and never overlapping.
    assert first.start_time == pytest.approx(1.0, abs=0.5)
    assert first.end_time == pytest.approx(3.0, abs=0.3)
    assert second.start_time >= first.end_time
    assert second.end_time == pytest.approx(5.5, abs=0.3)
    for segment in segments:
        seconds = len(segment.audio) / 2 / RATE
        assert seconds == pytest.approx(segment.end_time - segment.start_time, abs=0.01)
        assert audioop.rms(segment.audio, 2) > 500  # it is the speech, not the silence


def test_a_long_sentence_is_shown_in_parts_that_join_up():
    settings = StreamingSettings(**{**SETTINGS.__dict__, "max_segment_seconds": 2.0})

    segments, _, _, sarvam = _run(_speech(5.0) + _silence(1.0), settings=settings)

    assert len(segments) >= 2
    assert segments[0].cut_short and not segments[0].continues_previous
    assert segments[1].continues_previous
    assert not segments[-1].cut_short  # the pause ended the sentence
    assert sarvam.flushes >= 2  # the cuts, and the end of the stream
    for earlier, later in zip(segments, segments[1:]):
        assert later.start_time >= earlier.end_time


def test_what_is_still_being_said_when_the_stream_ends_is_not_lost():
    segments, failures, _, sarvam = _run(_silence(0.5) + _speech(1.5))

    assert failures == []
    assert [segment.transcript for segment in segments] == ["line 1"]
    assert segments[0].end_time == pytest.approx(2.0, abs=0.15)
    assert not segments[0].cut_short
    assert sarvam.closed


def test_a_language_this_system_does_not_take_is_left_for_the_ordinary_recogniser():
    segments, _, _, _ = _run(_speech(1.0) + _silence(1.0), ScriptedSarvam(language="hi-IN"))

    assert [segment.language for segment in segments] == [None]


def test_a_stretch_with_no_words_gives_no_line():
    segments, failures, _, _ = _run(_speech(1.0) + _silence(1.0), ScriptedSarvam(texts=["  "]))

    assert (segments, failures) == ([], [])


def test_long_silence_is_not_kept_in_memory():
    _, _, session, _ = _run(_silence(30.0))

    assert len(session.unheard_audio()) / 2 / RATE <= 4.0


def test_when_the_connection_cannot_be_made_all_the_audio_is_left_for_the_fallback():
    async def refuse(url, headers):
        raise OSError("no route")

    audio = _speech(1.0) + _silence(0.5)

    segments, failures, session, _ = _run(audio, connect=refuse)

    assert segments == []
    assert len(failures) == 1
    assert not session.alive
    # Everything fed before it failed, from the very start.
    unheard = session.unheard_audio()
    assert session.heard_until == 0.0
    assert unheard and audio.startswith(unheard)


def test_when_the_connection_drops_the_fallback_gets_what_was_not_answered_for():
    audio = _speech(1.0) + _silence(1.0) + _speech(2.0) + _silence(1.0)

    segments, failures, session, sarvam = _run(audio, ScriptedSarvam(break_after=3.0))

    assert [segment.transcript for segment in segments] == ["line 1"]
    assert len(failures) == 1
    # From the end of the line that was answered, to where the feed stopped.
    assert session.heard_until == pytest.approx(segments[0].end_time)
    assert len(session.unheard_audio()) / 2 / RATE >= 1.0
    assert audioop.rms(session.unheard_audio(), 2) > 500
    assert sarvam.closed  # the broken connection is let go


def test_only_8_and_16_khz_streams_are_taken():
    with pytest.raises(ValueError):
        SarvamStreamingSession(SETTINGS, 44100, lambda segment: None, lambda reason: None)


def _settings(**values) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_streaming_is_off_unless_it_is_asked_for_and_sarvam_is_the_recogniser():
    assert build_streaming_asr(_settings(asr_provider="sarvam", sarvam_api_key="k")) is None
    assert build_streaming_asr(_settings(live_asr_mode="streaming", asr_provider="whisper")) is None
    assert build_streaming_asr(_settings(live_asr_mode="streaming", asr_provider="sarvam")) is None

    factory = build_streaming_asr(
        _settings(
            live_asr_mode="streaming",
            asr_provider="sarvam",
            sarvam_api_key="k",
            asr_streaming_pause_frames=6,
        )
    )

    session = factory(8000, lambda segment: None, lambda reason: None)
    assert "wss://api.sarvam.ai/speech-to-text/ws?" in session.url()
    assert "negative_frames_count=6" in session.url() and "sample_rate=8000" in session.url()


# ---- A whole call's stream ----


def _stream_call(monkeypatch, sarvam: ScriptedSarvam, audio: bytes, call_uuid: str):
    """Stream the audio as a phone call with the streaming recogniser on.
    Returns (the ordinary recogniser, the call as stored)."""
    asr = _FakeASRProvider(transcript="heard in chunks")
    asked: list[str] = []
    identify = _FakeLanguageProvider.identify
    monkeypatch.setattr(
        _FakeLanguageProvider,
        "identify",
        lambda self, text: asked.append(text) or identify(self, text),
    )
    monkeypatch.setattr(
        "app.api.wiring.build_streaming_asr",
        lambda settings: lambda rate, on_segment, on_failure: SarvamStreamingSession(
            SETTINGS, rate, on_segment, on_failure, sarvam.connect
        ),
    )
    client, services = _build_client(monkeypatch, asr_provider=asr)
    call_id = _answer_call(client, call_uuid)
    frame = RATE // 50 * 2

    with client.websocket_connect(_stream_path(call_id)) as ws:
        ws.send_text(
            json.dumps(
                {
                    "event": "start",
                    "start": {"mediaFormat": {"encoding": "audio/x-l16", "sampleRate": RATE}},
                }
            )
        )
        _wait_for_stream(services, call_uuid, is_open=True)
        for index, start in enumerate(range(0, len(audio), frame)):
            payload = base64.b64encode(audio[start : start + frame]).decode()
            ws.send_text(
                json.dumps({"event": "media", "media": {"chunk": str(index + 1), "payload": payload}})
            )
        ws.send_text(json.dumps({"event": "stop"}))
        _wait_for_stream(services, call_uuid, is_open=False)

    asr.language_lookups = asked
    return asr, services.call_service.get_call(call_id)


def test_a_streamed_call_gets_its_lines_without_the_ordinary_recogniser(monkeypatch):
    sarvam = ScriptedSarvam(language="en-IN", texts=["my washing machine is leaking", "since monday"])
    audio = _silence(0.5) + _speech(2.0) + _silence(1.0) + _speech(1.0) + _silence(0.5)

    asr, call = _stream_call(monkeypatch, sarvam, audio, "uuid-streaming")

    assert asr.calls == []
    # Sarvam named the language with each line: it is not looked up again.
    assert asr.language_lookups == []
    assert [utterance.languages for utterance in call.utterances] == [("en",), ("en",)]
    assert [utterance.transcript for utterance in call.utterances] == [
        "my washing machine is leaking",
        "since monday",
    ]
    first, second = call.utterances
    assert first.start_time < first.end_time <= second.start_time < second.end_time
    assert second.end_time == pytest.approx(4.5, abs=0.4)


def test_a_call_whose_streaming_connection_drops_carries_on_in_chunks(monkeypatch):
    sarvam = ScriptedSarvam(language="en-IN", texts=["first line"], break_after=3.0)
    audio = _speech(1.0) + _silence(1.0) + _speech(3.0) + _silence(1.0)

    asr, call = _stream_call(monkeypatch, sarvam, audio, "uuid-streaming-drop")

    texts = [utterance.transcript for utterance in call.utterances]
    assert texts[0] == "first line"
    assert "heard in chunks" in texts[1]
    # The second stretch of speech reached the ordinary recogniser in full.
    assert asr.calls
    assert call.utterances[1].start_time >= call.utterances[0].end_time
