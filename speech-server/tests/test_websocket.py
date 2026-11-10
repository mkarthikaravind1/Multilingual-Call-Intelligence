import json
from starlette.testclient import TestClient
from tests.conftest import make_raw_pcm_bytes


def test_websocket_streaming_flow(client: TestClient):
    """
    Validates streaming protocol:
    speech_start -> speech_end -> transcript -> end.
    """
    with client.websocket_connect(
        "/v1/stream?language=ta&sample_rate=16000&pause_ms=250&max_segment_seconds=8"
    ) as ws:
        # 1. Send 1 second of speech (audio tone)
        speech_pcm = make_raw_pcm_bytes(
            duration_seconds=1.0,
            sample_rate=16000,
            frequency=400.0,
            amplitude=0.6,
        )
        ws.send_bytes(speech_pcm)

        # 2. Send 0.4 seconds of silence (exceeds pause_ms = 250ms)
        silence_pcm = make_raw_pcm_bytes(
            duration_seconds=0.4,
            sample_rate=16000,
            amplitude=0.0,
        )
        ws.send_bytes(silence_pcm)

        # 3. Read frames from server
        # First frame should be speech_start
        msg1 = json.loads(ws.receive_text())
        assert msg1["type"] == "speech_start"
        assert "at" in msg1

        # Second frame should be speech_end
        msg2 = json.loads(ws.receive_text())
        assert msg2["type"] == "speech_end"
        assert "at" in msg2

        # Third frame should be transcript
        msg3 = json.loads(ws.receive_text())
        assert msg3["type"] == "transcript"
        assert msg3["language"] == "ta"
        assert "text" in msg3
        assert "start" in msg3
        assert "end" in msg3

        # 4. End connection
        ws.send_text('{"type": "end"}')


def test_websocket_max_segment_seconds(client: TestClient):
    """
    Validates that speech continuing past max_segment_seconds emits speech_end
    and transcript before starting next chunk.
    """
    with client.websocket_connect(
        "/v1/stream?language=ta&sample_rate=16000&pause_ms=300&max_segment_seconds=1.0"
    ) as ws:
        # Send 1.5 seconds of continuous speech (exceeds max_segment_seconds = 1.0)
        long_speech = make_raw_pcm_bytes(
            duration_seconds=1.5,
            sample_rate=16000,
            frequency=400.0,
            amplitude=0.6,
        )
        ws.send_bytes(long_speech)

        # First frame: speech_start
        msg1 = json.loads(ws.receive_text())
        assert msg1["type"] == "speech_start"

        # Due to max_segment_seconds=1.0, it should cut and send speech_end
        msg2 = json.loads(ws.receive_text())
        assert msg2["type"] == "speech_end"

        # Followed by transcript
        msg3 = json.loads(ws.receive_text())
        assert msg3["type"] == "transcript"

        ws.send_text('{"type": "end"}')


def test_websocket_multiple_concurrent_connections(client: TestClient):
    """Verifies that 10 concurrent streams can connect and stream independently."""
    sockets = []
    try:
        for i in range(10):
            ws = client.websocket_connect(f"/v1/stream?language=en&sample_rate=16000").__enter__()
            sockets.append(ws)

        # Send audio through each
        pcm_chunk = make_raw_pcm_bytes(duration_seconds=0.5, amplitude=0.5)
        silence = make_raw_pcm_bytes(duration_seconds=0.3, amplitude=0.0)

        for ws in sockets:
            ws.send_bytes(pcm_chunk)
            ws.send_bytes(silence)

        for ws in sockets:
            m1 = json.loads(ws.receive_text())
            assert m1["type"] == "speech_start"
            m2 = json.loads(ws.receive_text())
            assert m2["type"] == "speech_end"
            m3 = json.loads(ws.receive_text())
            assert m3["type"] == "transcript"
            assert m3["language"] == "en"

        for ws in sockets:
            ws.send_text('{"type": "end"}')
    finally:
        for ws in sockets:
            try:
                ws.__exit__(None, None, None)
            except Exception:
                pass

