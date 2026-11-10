from starlette.testclient import TestClient
from app.config import get_settings
from tests.conftest import make_wav_bytes


def test_auth_not_configured_allows_access(client: TestClient):
    """When SPEECH_SERVER_TOKEN is not set, requests are allowed without auth."""
    settings = get_settings()
    settings.SPEECH_SERVER_TOKEN = None

    response = client.get("/health")
    assert response.status_code == 200

    audio_bytes = make_wav_bytes(duration_seconds=0.5)
    post_res = client.post(
        "/v1/transcribe",
        files={"file": ("sample.wav", audio_bytes, "audio/wav")},
    )
    assert post_res.status_code == 200


def test_auth_configured_requires_bearer_token(client: TestClient):
    """When SPEECH_SERVER_TOKEN is set, requests without valid token get 401."""
    settings = get_settings()
    settings.SPEECH_SERVER_TOKEN = "secret-token-123"

    # 1. No Authorization header -> 401
    res1 = client.get("/health")
    assert res1.status_code == 401

    # 2. Wrong token -> 401
    res2 = client.get("/health", headers={"Authorization": "Bearer wrong-token"})
    assert res2.status_code == 401

    # 3. Invalid scheme -> 401
    res3 = client.get("/health", headers={"Authorization": "Basic secret-token-123"})
    assert res3.status_code == 401

    # 4. Correct token -> 200
    res4 = client.get("/health", headers={"Authorization": "Bearer secret-token-123"})
    assert res4.status_code == 200

    # 5. POST /v1/transcribe with token -> 200
    audio_bytes = make_wav_bytes(duration_seconds=0.5)
    res5 = client.post(
        "/v1/transcribe",
        headers={"Authorization": "Bearer secret-token-123"},
        files={"file": ("sample.wav", audio_bytes, "audio/wav")},
    )
    assert res5.status_code == 200


def test_websocket_auth(client: TestClient):
    """WebSocket connection auth validation."""
    settings = get_settings()
    settings.SPEECH_SERVER_TOKEN = "secret-token-123"

    # Connection without token should be rejected
    try:
        with client.websocket_connect("/v1/stream") as ws:
            pass
        assert False, "Expected WebSocket to be rejected"
    except Exception:
        # Expected closure due to 1008 policy violation
        pass

    # Connection with query token should succeed
    with client.websocket_connect("/v1/stream?token=secret-token-123") as ws:
        ws.send_text('{"type": "end"}')

