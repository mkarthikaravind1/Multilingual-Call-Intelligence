from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from app.api.app_factory import create_app
from app.api.security_headers import SecurityHeadersMiddleware


def _client(*, hsts: bool) -> TestClient:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, hsts=hsts)

    @app.get("/plain")
    def plain():
        return {"ok": True}

    @app.get("/custom")
    def custom():
        return PlainTextResponse("x", headers={"X-Frame-Options": "SAMEORIGIN"})

    return TestClient(app)


def test_adds_baseline_headers():
    response = _client(hsts=False).get("/plain")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" not in response.headers


def test_hsts_only_when_enabled():
    response = _client(hsts=True).get("/plain")

    assert "max-age=" in response.headers["strict-transport-security"]


def test_does_not_overwrite_headers_a_route_set():
    response = _client(hsts=False).get("/custom")

    assert response.headers.get_list("x-frame-options") == ["SAMEORIGIN"]


def test_real_app_sets_headers_on_success_and_error_responses():
    from tests.test_production_readiness import _services

    client = TestClient(create_app(_services()))

    for response in (client.get("/health/live"), client.get("/api/v1/no-such-route")):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
