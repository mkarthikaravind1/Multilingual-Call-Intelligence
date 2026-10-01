"""Test calls: a supervisor replays a recording through the telephony path."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.domain.user import User, UserRole
from app.security.jwt import create_access_token
from app.security.stream_token import is_valid_stream_token
from tests.test_call_customer import CRM, build_client


@pytest.fixture
def crm_file(tmp_path):
    path = tmp_path / "crm.json"
    path.write_text(json.dumps(CRM), encoding="utf-8")
    return path


def _as(client: TestClient, services, role: UserRole) -> TestClient:
    user = User(
        user_id=f"user-{role.value}",
        email=f"{role.value.lower()}@example.com",
        password_hash="unused",
        role=role,
        is_active=True,
        created_at=time.time(),
    )
    services.user_repository.save(user)
    return TestClient(client.app, headers={"Authorization": f"Bearer {create_access_token(user)}"})


@pytest.fixture
def supervisor(crm_file):
    client, services, _ = build_client(crm_file)
    return _as(client, services, UserRole.SUPERVISOR), client, services


def test_start_creates_a_telephony_call_with_the_caller_identified(supervisor):
    client, _, services = supervisor

    response = client.post("/api/v1/test-calls", json={"from_number": "9845000002"})

    assert response.status_code == 201
    body = response.json()
    call_id = body["call_id"]
    assert call_id.startswith("test-")
    assert body["provider_call_id"].startswith("test-")
    assert body["stream_path"].startswith(f"/api/v1/calls/{call_id}/telephony-stream?token=")
    token = body["stream_path"].split("token=", 1)[1]
    assert is_valid_stream_token(token, call_id, get_settings())
    assert client.get(f"/api/v1/calls/{call_id}").json()["status"].lower() == "active"
    assert client.get(f"/api/v1/calls/{call_id}/customer").json()["customer"]["customer_id"] == "C-2"


def test_end_completes_the_call(supervisor):
    client, _, _ = supervisor
    started = client.post("/api/v1/test-calls", json={}).json()

    response = client.post(
        f"/api/v1/test-calls/{started['provider_call_id']}/end", json={"duration_seconds": 12.5}
    )

    assert response.status_code == 202
    assert client.get(f"/api/v1/calls/{started['call_id']}").json()["status"].lower() == "completed"
    # A repeated hang-up is harmless.
    assert (
        client.post(f"/api/v1/test-calls/{started['provider_call_id']}/end", json={}).status_code
        == 202
    )


def test_end_rejects_unknown_and_non_test_calls(supervisor):
    client, _, _ = supervisor

    assert client.post("/api/v1/test-calls/test-missing/end", json={}).status_code == 404
    assert client.post("/api/v1/test-calls/plivo-uuid/end", json={}).status_code == 404


def test_only_supervisors_and_admins_can_run_test_calls(crm_file):
    icr_client, services, _ = build_client(crm_file)

    assert icr_client.post("/api/v1/test-calls", json={}).status_code == 403
    assert _as(icr_client, services, UserRole.ADMIN).post("/api/v1/test-calls", json={}).status_code == 201
    assert TestClient(icr_client.app).post("/api/v1/test-calls", json={}).status_code == 401


def test_test_calls_are_disabled_in_production(crm_file, monkeypatch):
    client, services, _ = build_client(crm_file)
    supervisor = _as(client, services, UserRole.SUPERVISOR)
    production = Settings(_env_file=None, app_env="production")  # type: ignore[call-arg]
    monkeypatch.setattr("app.api.v1.test_calls.get_settings", lambda: production)

    assert supervisor.post("/api/v1/test-calls", json={}).status_code == 404
