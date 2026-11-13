from starlette.testclient import TestClient
from app.main import app


def test_health_ok(client: TestClient, setup_fake_engine):
    """GET /health returns 200 with model and device info when loaded."""
    setup_fake_engine.set_loaded(True)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["model"] == "mock-indic-whisper"
    assert data["device"] in ("cpu", "cuda")


def test_health_loading_returns_503(client: TestClient, setup_fake_engine):
    """GET /health returns 503 while the engine is still loading."""
    setup_fake_engine.set_loaded(False)
    response = client.get("/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "loading"

