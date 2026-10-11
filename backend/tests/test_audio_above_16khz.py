"""Audio sampled above 16 kHz (the SRD allows up to 48 kHz) is brought down
to 16 kHz as it arrives: the speech recogniser takes no more, and the
chunks, the transcript times and the recording are all made from that."""

import base64
import io
import json
import math
import struct
import wave

import pytest

from app.services.telephony_audio_buffer import (
    MAX_PROCESSING_SAMPLE_RATE,
    Downsampler,
    TelephonyAudioBufferError,
)
from tests.test_telephony import (
    _answer_call,
    _build_client,
    _FakeASRProvider,
    _stream_path,
    _wait_for_stream,
)


def _tone(rate: int, seconds: float, hertz: float = 440.0) -> bytes:
    count = int(rate * seconds)
    return b"".join(
        struct.pack("<h", int(12000 * math.sin(2 * math.pi * hertz * n / rate))) for n in range(count)
    )


def _loudest_frequency(pcm: bytes, rate: int) -> float:
    """Counted from zero crossings: enough to tell 440 Hz from its octave."""
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    crossings = sum(1 for a, b in zip(samples, samples[1:]) if (a < 0) != (b < 0))
    return crossings / 2 / (len(samples) / rate)


@pytest.mark.parametrize("rate", [24000, 32000, 44100, 48000])
def test_audio_above_16_khz_comes_out_at_16_khz_the_same_length_and_pitch(rate):
    down = Downsampler(rate)

    converted = down.convert(None, _tone(rate, 1.0))

    assert (down.rate, down.converts) == (16000, True)
    assert len(converted) / 2 == pytest.approx(16000, abs=4)  # still one second
    assert _loudest_frequency(converted, 16000) == pytest.approx(440, abs=3)


@pytest.mark.parametrize("rate", [8000, 16000])
def test_audio_at_16_khz_or_below_is_not_touched(rate):
    down = Downsampler(rate)
    audio = _tone(rate, 0.2)

    assert (down.rate, down.converts) == (rate, False)
    assert down.convert(None, audio) is audio


def test_frames_converted_one_at_a_time_join_without_a_gap():
    audio = _tone(48000, 1.0)
    whole = Downsampler(48000).convert(None, audio)
    down = Downsampler(48000)
    frame = 48000 // 50 * 2  # 20 ms, as a phone stream sends them

    pieces = b"".join(
        down.convert(None, audio[start : start + frame]) for start in range(0, len(audio), frame)
    )

    assert len(pieces) == pytest.approx(len(whole), abs=8)
    assert _loudest_frequency(pieces, 16000) == pytest.approx(440, abs=3)


def test_each_track_is_converted_on_its_own():
    down = Downsampler(48000)
    caller, executive = _tone(48000, 0.5, 440.0), _tone(48000, 0.5, 880.0)
    half = len(caller) // 2

    first = down.convert("inbound", caller[:half]) + down.convert("inbound", caller[half:])
    down.convert("outbound", executive)

    assert _loudest_frequency(first, 16000) == pytest.approx(440, abs=5)


def test_empty_and_odd_sized_frames_are_handled():
    down = Downsampler(48000)

    assert down.convert(None, b"") == b""
    assert len(down.convert(None, _tone(48000, 0.1) + b"\x01")) % 2 == 0
    with pytest.raises(TelephonyAudioBufferError):
        Downsampler(0)


def test_a_48_khz_stream_reaches_the_recogniser_as_16_khz(monkeypatch):
    asr = _FakeASRProvider()
    client, services = _build_client(monkeypatch, asr_provider=asr)
    call_id = _answer_call(client, "uuid-48k")
    audio = _tone(48000, 1.0)
    frame = 48000 // 50 * 2

    with client.websocket_connect(_stream_path(call_id)) as ws:
        ws.send_text(
            json.dumps(
                {
                    "event": "start",
                    "start": {"mediaFormat": {"encoding": "audio/x-l16", "sampleRate": 48000}},
                }
            )
        )
        _wait_for_stream(services, "uuid-48k", is_open=True)
        for index, start in enumerate(range(0, len(audio), frame)):
            payload = base64.b64encode(audio[start : start + frame]).decode()
            ws.send_text(
                json.dumps({"event": "media", "media": {"chunk": str(index + 1), "payload": payload}})
            )
        ws.send_text(json.dumps({"event": "stop"}))
        _wait_for_stream(services, "uuid-48k", is_open=False)

    assert asr.calls, "nothing reached the speech recogniser"
    seconds = 0.0
    for chunk in asr.calls:
        with wave.open(io.BytesIO(chunk)) as heard:
            assert heard.getframerate() == MAX_PROCESSING_SAMPLE_RATE
            seconds += heard.getnframes() / heard.getframerate()
    assert seconds == pytest.approx(1.0, abs=0.05)
    assert services.call_service.get_call(call_id).utterance_count >= 1
