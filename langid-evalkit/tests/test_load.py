"""Unit tests for evalkit.load: Load testing and latency calculations."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch

from evalkit.load.runner import percentile, run_load_test


def test_percentile():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(vals, 50.0) == 3.0
    assert percentile(vals, 0.0) == 1.0
    assert percentile(vals, 100.0) == 5.0
    assert percentile([], 50.0) == 0.0

    # 95th percentile
    vals_100 = list(range(1, 101))
    assert percentile(vals_100, 95.0) == 95.05 or abs(percentile(vals_100, 95.0) - 95.0) <= 1.0


@pytest.mark.asyncio
async def test_run_load_test_mocked():
    # Mock WebSocket connection
    class MockWS:
        def __init__(self):
            self.sent = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def send(self, data):
            self.sent.append(data)

        def __aiter__(self):
            return self

        async def __anext__(self):
            # Send 2 transcript lines then stop
            if not hasattr(self, "_count"):
                self._count = 0
            if self._count < 2:
                self._count += 1
                await asyncio.sleep(0.01)
                return json.dumps({
                    "type": "transcript",
                    "text": "வணக்கம் சார்",
                    "start": 0.0,
                    "end": 0.2,
                })
            raise StopAsyncIteration

    # Mock HTTP response
    class MockHTTPResponse:
        def __init__(self):
            self.status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}]}

    with patch("websockets.connect", return_value=MockWS()):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MockHTTPResponse()

            metrics = await run_load_test(
                speech_url="ws://mock-speech:8000",
                llm_url="http://mock-llm:8001",
                num_calls=2,
                call_duration_sec=0.2,
                llm_interval_sec=0.1,
            )

            assert metrics["num_calls"] == 2
            assert "transcripts" in metrics
            assert "llm" in metrics
            assert metrics["transcripts"]["total_lines_received"] >= 2
            assert metrics["llm"]["total_answers_received"] >= 2
            assert metrics["transcripts"]["p50_latency_sec"] >= 0.0
            assert metrics["llm"]["p95_latency_sec"] >= 0.0

