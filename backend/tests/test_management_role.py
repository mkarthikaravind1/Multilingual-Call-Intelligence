"""The management role: reads reports and the finished calls behind them,
and nothing else. Every other endpoint refuses it, including ones added
later (the role is let in only where an endpoint names it)."""

import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentLabel, SentimentResult
from app.api.app_factory import API_V1_PREFIX, create_app
from app.api.wiring import build_api_services
from app.core.config import Settings
from app.domain.user import User, UserRole
from app.security.jwt import create_access_token, decode_access_token
from app.security.stream_token import create_live_call_ticket
from app.services.audit_log import AuditFilter


class _NoComplaints(ComplaintDetectionProvider):
    def detect(self, conversation, learning_context=()):
        return []


class _Calm(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEUTRAL, 0.7, "Calm.")


class _NoQuestions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


class _Api:
    def __init__(self) -> None:
        self.services = build_api_services(
            _NoComplaints(), _Calm(), _NoQuestions(), Settings(_env_file=None)  # type: ignore[call-arg]
        )
        self.client = TestClient(create_app(self.services))

    def user(self, user_id: str, role: UserRole) -> dict[str, str]:
        user = User(user_id, f"{user_id}@example.com", "hash", role, True, time.time())
        self.services.user_repository.save(user)
        return {"Authorization": f"Bearer {create_access_token(user)}"}

    def call(self, call_id: str, finished: bool) -> str:
        icr = self.user("icr-1", UserRole.ICR)
        assert self.client.post("/api/v1/calls", json={"call_id": call_id}, headers=icr).status_code == 201
        if finished:
            assert self.client.post(f"/api/v1/calls/{call_id}/complete", json={}, headers=icr).status_code == 200
        return call_id


@pytest.fixture
def api() -> _Api:
    return _Api()


# What a management user may call. Everything else must refuse them.
ALLOWED = {
    ("GET", "/reports/complaints"),
    ("GET", "/reports/complaints/export"),
    ("GET", "/reports/performance"),
    ("GET", "/reports/performance/export"),
    ("GET", "/reports/calls/{call_id}/audit"),
    # What the report filters offer.
    ("GET", "/call-directory"),
    ("GET", "/complaints/categories"),
    # A finished call, opened from a report.
    ("GET", "/calls/{call_id}"),
    ("GET", "/calls/{call_id}/analysis"),
    # Staying signed in.
    ("POST", "/auth/refresh"),
}
# No user signs in to these: the public sign-in, the telephony provider's
# webhooks (signed by the provider) and the probes.
NOT_FOR_USERS = ("/auth/login", "/telephony/", "/health/", "/metrics")


def _endpoints(api: _Api) -> list[tuple[str, str]]:
    return sorted(
        (method.upper(), path)
        for path, methods in api.client.app.openapi()["paths"].items()
        for method in methods
        if not any(part in path for part in NOT_FOR_USERS)
    )


def _send(api: _Api, method: str, path: str, headers: dict[str, str], call_id: str):
    address = path.replace("{call_id}", call_id)
    for name in ("user_id", "location_id", "key", "complaint_id", "candidate_id", "entry_id",
                 "version_id", "provider_call_id", "improvement_id"):
        address = address.replace("{" + name + "}", "1")
    assert "{" not in address, f"unfilled address: {path}"
    return api.client.request(method, address, json={}, headers=headers)


def test_everything_outside_reports_refuses_a_management_user(api):
    management = api.user("mgmt-1", UserRole.MANAGEMENT)
    call_id = api.call("finished-call", finished=True)
    endpoints = _endpoints(api)
    assert len(endpoints) > 60  # the whole API was listed, not a part of it

    let_in = set()
    for method, path in endpoints:
        response = _send(api, method, path, management, call_id)
        # Test calls are switched off here and say 404 to everyone.
        refused = response.status_code == 403 or (
            path.startswith(f"{API_V1_PREFIX}/test-calls") and response.status_code == 404
        )
        if not refused:
            let_in.add((method, path.removeprefix(API_V1_PREFIX)))

    assert let_in == ALLOWED


def test_staff_are_let_in_where_they_were_before(api):
    """The same sweep as a supervisor: nothing but the administration
    refuses them, so the rule took nothing away from staff."""
    supervisor = api.user("sup-1", UserRole.SUPERVISOR)
    call_id = api.call("finished-call", finished=True)

    refused = {
        path.removeprefix(API_V1_PREFIX)
        for method, path in _endpoints(api)
        if _send(api, method, path, supervisor, call_id).status_code == 403
    }

    assert refused
    assert all(
        path.startswith(("/admin/", "/learning/training-data")) for path in refused
    ), refused
    # The post-call repair list is theirs as well as the admin's.
    assert not any(path.startswith("/admin/post-call") for path in refused), refused


@pytest.mark.parametrize(
    "url",
    [
        "/api/v1/reports/complaints?started_from=0&started_to=86400",
        "/api/v1/reports/complaints/export?started_from=0&started_to=86400&format=csv",
        "/api/v1/reports/performance?started_from=0&started_to=86400",
        "/api/v1/reports/performance/export?started_from=0&started_to=86400&format=csv",
        "/api/v1/call-directory",
        "/api/v1/complaints/categories",
    ],
)
def test_a_management_user_reads_the_reports_and_their_filters(api, url):
    management = api.user("mgmt-1", UserRole.MANAGEMENT)

    assert api.client.get(url, headers=management).status_code == 200
    # An executive still cannot.
    icr = api.user("icr-1", UserRole.ICR)
    if "/reports/" in url:
        assert api.client.get(url, headers=icr).status_code == 403


def test_a_management_user_opens_a_finished_call_with_its_analysis_and_audit(api):
    management = api.user("mgmt-1", UserRole.MANAGEMENT)
    call_id = api.call("finished-call", finished=True)

    call = api.client.get(f"/api/v1/calls/{call_id}", headers=management)
    analysis = api.client.get(f"/api/v1/calls/{call_id}/analysis", headers=management)
    audit = api.client.get(f"/api/v1/reports/calls/{call_id}/audit", headers=management)

    assert (call.status_code, analysis.status_code, audit.status_code) == (200, 200, 200)
    assert call.json()["call_id"] == call_id


def test_a_management_user_cannot_open_a_call_in_progress(api):
    management = api.user("mgmt-1", UserRole.MANAGEMENT)
    call_id = api.call("live-call", finished=False)

    for url in (f"/api/v1/calls/{call_id}", f"/api/v1/calls/{call_id}/analysis"):
        response = api.client.get(url, headers=management)
        assert response.status_code == 403
        assert response.json()["detail"] == "This call can be opened once it has ended."

    # The executive on the call reads it as before.
    icr = api.user("icr-1", UserRole.ICR)
    assert api.client.get(f"/api/v1/calls/{call_id}", headers=icr).status_code == 200


def test_an_unknown_call_is_not_found_for_a_management_user_too(api):
    management = api.user("mgmt-1", UserRole.MANAGEMENT)

    assert api.client.get("/api/v1/calls/nope", headers=management).status_code == 404
    assert api.client.get("/api/v1/calls/nope/analysis", headers=management).status_code == 404


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "/api/v1/calls"),
        ("GET", "/api/v1/live-calls"),
        ("GET", "/api/v1/call-stats"),
        ("POST", "/api/v1/calls"),
        ("POST", "/api/v1/calls/finished-call/utterances"),
        ("GET", "/api/v1/calls/finished-call/customer"),
        ("GET", "/api/v1/calls/finished-call/complaints"),
        ("GET", "/api/v1/calls/finished-call/recording"),
        ("POST", "/api/v1/calls/finished-call/live-token"),
        ("GET", "/api/v1/complaints"),
        ("GET", "/api/v1/escalations"),
        ("GET", "/api/v1/learning/candidates"),
        ("GET", "/api/v1/admin/users"),
        ("GET", "/api/v1/admin/audit-log"),
        ("GET", "/api/v1/price-list"),
    ],
)
def test_a_management_user_is_refused_the_rest_by_name(api, method, url):
    management = api.user("mgmt-1", UserRole.MANAGEMENT)
    api.call("finished-call", finished=True)

    assert api.client.request(method, url, json={}, headers=management).status_code == 403


def test_the_live_view_refuses_a_management_user_even_with_a_ticket(api):
    api.user("mgmt-1", UserRole.MANAGEMENT)
    call_id = api.call("live-call", finished=False)
    ticket = create_live_call_ticket("mgmt-1", call_id).token

    with api.client.websocket_connect(f"/api/v1/calls/{call_id}/live?ticket={ticket}") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()

    assert closed.value.code == 4401


def test_a_refused_request_is_in_the_audit_log_under_the_role(api):
    management = api.user("mgmt-1", UserRole.MANAGEMENT)

    api.client.post("/api/v1/calls", json={"call_id": "c1"}, headers=management)
    api.services.audit_log.flush()

    (entry,) = api.services.audit_log.search(AuditFilter(user_id="mgmt-1")).entries
    assert (entry.role, entry.action, entry.status_code) == ("MANAGEMENT", "start_call", 403)


def test_a_management_user_stays_signed_in_and_keeps_the_role(api):
    management = api.user("mgmt-1", UserRole.MANAGEMENT)

    response = api.client.post("/api/v1/auth/refresh", headers=management)

    assert response.status_code == 200
    assert decode_access_token(response.json()["access_token"])["role"] == "MANAGEMENT"


# ---- Administration ----


def test_an_admin_creates_a_management_user_who_is_given_no_location_or_phone(api):
    admin = api.user("admin-1", UserRole.ADMIN)
    api.services.location_service.create_location("Chennai", "+914400000001")
    location_id = api.services.location_service.list_locations()[0].location_id

    response = api.client.post(
        "/api/v1/admin/users",
        json={
            "email": "director@example.com",
            "password": "a-long-password",
            "role": "MANAGEMENT",
            "display_name": "The Director",
            "location_id": location_id,
            "dial_target": "+919800000001",
        },
        headers=admin,
    )

    body = response.json()
    assert response.status_code == 201
    assert (body["role"], body["display_name"]) == ("MANAGEMENT", "The Director")
    assert (body["location_id"], body["dial_target"]) == (None, None)


def test_a_user_moved_to_management_loses_the_location_and_phone(api):
    admin = api.user("admin-1", UserRole.ADMIN)
    location = api.services.location_service.create_location("Chennai", "+914400000001")
    created = api.client.post(
        "/api/v1/admin/users",
        json={
            "email": "exec@example.com",
            "password": "a-long-password",
            "role": "ICR",
            "location_id": location.location_id,
            "dial_target": "+919800000001",
        },
        headers=admin,
    ).json()
    assert created["dial_target"] == "+919800000001"

    moved = api.client.patch(
        f"/api/v1/admin/users/{created['user_id']}", json={"role": "MANAGEMENT"}, headers=admin
    ).json()

    assert (moved["role"], moved["location_id"], moved["dial_target"]) == ("MANAGEMENT", None, None)
    # So an incoming call never rings them.
    assert api.services.user_repository.get_by_id(created["user_id"]).dial_target is None


def test_management_users_are_not_offered_as_executives(api):
    management = api.user("mgmt-1", UserRole.MANAGEMENT)
    api.user("icr-1", UserRole.ICR)
    api.user("sup-1", UserRole.SUPERVISOR)

    directory = api.client.get("/api/v1/call-directory", headers=management).json()

    assert {entry["id"] for entry in directory["executives"]} == {"icr-1", "sup-1"}
