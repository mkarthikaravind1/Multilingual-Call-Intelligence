"""The admin role: sets the system up and keeps it working, reads the
reports, the call list and finished calls. It takes no calls and does
none of the supervisor's work, and every endpoint that does not name the
role refuses it, including ones added later."""

import time

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api.app_factory import API_V1_PREFIX
from app.domain.conversation import CallDirection
from app.domain.location import Location
from app.domain.user import User, UserRole
from app.security.jwt import decode_access_token
from app.security.stream_token import create_live_call_ticket
from app.services.audit_log import AuditFilter
from app.services.call_routing_service import CallRoutingService
from tests.test_management_role import _Api, _endpoints, _send


@pytest.fixture
def api() -> _Api:
    return _Api()


# What an admin may call besides /admin/... and /reports/..., all of which
# are theirs. Everything else must refuse them.
ALLOWED = {
    # The read-only dashboard.
    ("GET", "/calls"),
    ("GET", "/call-stats"),
    # What the dashboard's and the reports' filters offer.
    ("GET", "/call-directory"),
    ("GET", "/complaints/categories"),
    # A finished call.
    ("GET", "/calls/{call_id}"),
    ("GET", "/calls/{call_id}/analysis"),
    # The file of reviewed AI outputs.
    ("GET", "/learning/training-data"),
    ("GET", "/learning/training-data/export"),
    # Staying signed in.
    ("POST", "/auth/refresh"),
}
OWN_AREAS = ("/admin/", "/reports/")


def _let_in(api: _Api, headers: dict[str, str], call_id: str) -> set[tuple[str, str]]:
    let_in = set()
    for method, path in _endpoints(api):
        response = _send(api, method, path, headers, call_id)
        if response.status_code != 403:
            let_in.add((method, path.removeprefix(API_V1_PREFIX)))
    return let_in


def test_an_admin_is_let_in_to_administration_reports_and_reading_and_nothing_else(api):
    admin = api.user("admin-1", UserRole.ADMIN)
    call_id = api.call("finished-call", finished=True)
    endpoints = {(method, path.removeprefix(API_V1_PREFIX)) for method, path in _endpoints(api)}
    assert len(endpoints) > 60  # the whole API was listed, not a part of it

    let_in = _let_in(api, admin, call_id)

    own = {endpoint for endpoint in endpoints if endpoint[1].startswith(OWN_AREAS)}
    assert len(own) > 20
    assert let_in == ALLOWED | own


@pytest.mark.parametrize(
    ("method", "url"),
    [
        # Taking a call and working on it.
        ("POST", "/api/v1/calls"),
        ("POST", "/api/v1/calls/finished-call/utterances"),
        ("POST", "/api/v1/calls/finished-call/complete"),
        ("POST", "/api/v1/calls/finished-call/hold"),
        ("POST", "/api/v1/calls/finished-call/resume"),
        ("POST", "/api/v1/calls/finished-call/question-outcomes"),
        ("GET", "/api/v1/calls/finished-call/customer"),
        ("PUT", "/api/v1/calls/finished-call/customer"),
        ("PUT", "/api/v1/calls/finished-call/customer/vehicle"),
        ("GET", "/api/v1/calls/finished-call/summary-delivery"),
        ("POST", "/api/v1/calls/finished-call/live-token"),
        ("POST", "/api/v1/learning/calls/finished-call/feedback"),
        # Complaints.
        ("GET", "/api/v1/complaints"),
        ("GET", "/api/v1/calls/finished-call/complaints"),
        ("POST", "/api/v1/complaints/1/status"),
        # The supervisor's work.
        ("GET", "/api/v1/live-calls"),
        ("GET", "/api/v1/escalations"),
        ("GET", "/api/v1/escalations/stats"),
        ("POST", "/api/v1/escalations/finished-call/acknowledge"),
        ("POST", "/api/v1/escalations/finished-call/resolve"),
        ("GET", "/api/v1/calls/finished-call/recording"),
        ("GET", "/api/v1/calls/finished-call/recording/audio"),
        ("GET", "/api/v1/learning/candidates"),
        ("POST", "/api/v1/learning/candidates/1/approve"),
        ("POST", "/api/v1/learning/candidates/1/reject"),
        ("POST", "/api/v1/learning/improvements/1/deactivate"),
        ("GET", "/api/v1/emerging-complaints"),
        ("POST", "/api/v1/emerging-complaints/discover"),
        ("POST", "/api/v1/emerging-complaints/1/review"),
        ("GET", "/api/v1/price-list"),
    ],
)
def test_an_admin_is_refused_the_work_on_calls_by_name(api, method, url):
    admin = api.user("admin-1", UserRole.ADMIN)
    api.call("finished-call", finished=True)

    assert api.client.request(method, url, json={}, headers=admin).status_code == 403


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "/api/v1/live-calls"),
        ("GET", "/api/v1/escalations"),
        ("GET", "/api/v1/calls/finished-call/recording"),
        ("GET", "/api/v1/learning/candidates"),
        ("GET", "/api/v1/emerging-complaints"),
        ("GET", "/api/v1/complaints"),
        ("GET", "/api/v1/calls/finished-call/customer"),
        ("GET", "/api/v1/admin/post-call"),
    ],
)
def test_a_supervisor_keeps_what_the_admin_lost(api, method, url):
    supervisor = api.user("sup-1", UserRole.SUPERVISOR)
    api.call("finished-call", finished=True)

    assert api.client.request(method, url, headers=supervisor).status_code == 200


# ---- Calls: the list, and a call once it has ended ----


def test_an_admin_reads_the_call_list_and_counts_with_calls_in_progress_listed(api):
    admin = api.user("admin-1", UserRole.ADMIN)
    api.call("finished-call", finished=True)
    api.call("live-call", finished=False)

    listed = api.client.get("/api/v1/calls", headers=admin)
    counts = api.client.get("/api/v1/call-stats", headers=admin)

    assert (listed.status_code, counts.status_code) == (200, 200)
    assert {call["call_id"] for call in listed.json()["items"]} == {"finished-call", "live-call"}
    assert (counts.json()["active"], counts.json()["completed"]) == (1, 1)


def test_an_admin_opens_a_finished_call_with_its_analysis_and_audit(api):
    admin = api.user("admin-1", UserRole.ADMIN)
    call_id = api.call("finished-call", finished=True)

    call = api.client.get(f"/api/v1/calls/{call_id}", headers=admin)
    analysis = api.client.get(f"/api/v1/calls/{call_id}/analysis", headers=admin)
    audit = api.client.get(f"/api/v1/reports/calls/{call_id}/audit", headers=admin)

    assert (call.status_code, analysis.status_code, audit.status_code) == (200, 200, 200)
    assert call.json()["call_id"] == call_id


def test_an_admin_cannot_open_a_call_in_progress(api):
    admin = api.user("admin-1", UserRole.ADMIN)
    call_id = api.call("live-call", finished=False)

    for url in (f"/api/v1/calls/{call_id}", f"/api/v1/calls/{call_id}/analysis"):
        response = api.client.get(url, headers=admin)
        assert response.status_code == 403
        assert response.json()["detail"] == "This call can be opened once it has ended."

    # A supervisor reads it as before, and the admin can once it ends.
    supervisor = api.user("sup-1", UserRole.SUPERVISOR)
    assert api.client.get(f"/api/v1/calls/{call_id}", headers=supervisor).status_code == 200
    api.client.post(f"/api/v1/calls/{call_id}/complete", json={}, headers=supervisor)
    assert api.client.get(f"/api/v1/calls/{call_id}", headers=admin).status_code == 200


def test_an_unknown_call_is_not_found_for_an_admin_too(api):
    admin = api.user("admin-1", UserRole.ADMIN)

    assert api.client.get("/api/v1/calls/nope", headers=admin).status_code == 404
    assert api.client.get("/api/v1/calls/nope/analysis", headers=admin).status_code == 404


def test_the_live_view_refuses_an_admin_even_with_a_ticket(api):
    api.user("admin-1", UserRole.ADMIN)
    call_id = api.call("live-call", finished=False)
    ticket = create_live_call_ticket("admin-1", call_id).token

    with api.client.websocket_connect(f"/api/v1/calls/{call_id}/live?ticket={ticket}") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()

    assert closed.value.code == 4401


def test_an_admin_retries_post_call_processing_and_reads_the_repair_list(api):
    admin = api.user("admin-1", UserRole.ADMIN)
    call_id = api.call("finished-call", finished=True)

    assert api.client.get("/api/v1/admin/post-call", headers=admin).status_code == 200
    retried = api.client.post(f"/api/v1/admin/post-call/{call_id}/retry", headers=admin)

    assert retried.status_code == 200
    assert retried.json()["call_id"] == call_id


def test_a_refused_request_is_in_the_audit_log_under_the_role(api):
    admin = api.user("admin-1", UserRole.ADMIN)

    api.client.post("/api/v1/calls", json={"call_id": "c1"}, headers=admin)
    api.services.audit_log.flush()

    (entry,) = api.services.audit_log.search(AuditFilter(user_id="admin-1")).entries
    assert (entry.role, entry.action, entry.status_code) == ("ADMIN", "start_call", 403)


def test_an_admin_stays_signed_in_and_keeps_the_role(api):
    admin = api.user("admin-1", UserRole.ADMIN)

    response = api.client.post("/api/v1/auth/refresh", headers=admin)

    assert response.status_code == 200
    assert decode_access_token(response.json()["access_token"])["role"] == "ADMIN"


# ---- An admin takes no calls ----


def _new_user(api: _Api, admin: dict[str, str], role: str, location_id: str, email: str) -> dict:
    response = api.client.post(
        "/api/v1/admin/users",
        json={
            "email": email,
            "password": "a-long-password",
            "role": role,
            "location_id": location_id,
            "dial_target": "+919800000001",
        },
        headers=admin,
    )
    assert response.status_code == 201
    return response.json()


def test_a_new_admin_is_given_no_location_or_phone(api):
    admin = api.user("admin-1", UserRole.ADMIN)
    location = api.services.location_service.create_location("Chennai", "+914400000001")

    created = _new_user(api, admin, "ADMIN", location.location_id, "second-admin@example.com")

    assert (created["role"], created["location_id"], created["dial_target"]) == ("ADMIN", None, None)


def test_a_user_moved_to_admin_loses_the_location_and_phone(api):
    admin = api.user("admin-1", UserRole.ADMIN)
    location = api.services.location_service.create_location("Chennai", "+914400000001")
    created = _new_user(api, admin, "SUPERVISOR", location.location_id, "lead@example.com")
    assert created["dial_target"] == "+919800000001"

    moved = api.client.patch(
        f"/api/v1/admin/users/{created['user_id']}", json={"role": "ADMIN"}, headers=admin
    ).json()

    assert (moved["role"], moved["location_id"], moved["dial_target"]) == ("ADMIN", None, None)
    assert api.services.user_repository.get_by_id(created["user_id"]).dial_target is None


def _admin_from_before(api: _Api, location_id: str) -> User:
    """An admin who still has the location and phone the role once had."""
    user = User(
        "old-admin",
        "old-admin@example.com",
        "hash",
        UserRole.ADMIN,
        True,
        time.time(),
        location_id=location_id,
        dial_target="+919800000009",
    )
    api.services.user_repository.save(user)
    return user


def test_an_admin_with_a_phone_from_before_is_never_rung_or_given_a_call(api):
    location = api.services.location_service.create_location("Chennai", "+914400000001")
    _admin_from_before(api, location.location_id)
    icr = User(
        "icr-9", "icr-9@example.com", "hash", UserRole.ICR, True, time.time(),
        location_id=location.location_id, dial_target="+919800000001",
    )
    api.services.user_repository.save(icr)
    routing = CallRoutingService(
        _Locations([location]), api.services.user_repository, default_country_code="91"
    )

    incoming = routing.route("+919000000001", "+914400000001")
    from_the_admin = routing.route("+919800000009", "+919000000001")

    # Only the executive's phone rings.
    assert incoming.dial_targets == ("+919800000001",)
    # A call from the admin's old phone is not an executive's outgoing call.
    assert from_the_admin.direction is CallDirection.INBOUND
    assert from_the_admin.executive_user_id is None
    assert routing.executive_for_target("+919800000009") is None
    assert routing.executive_for_target("+919800000001") == icr


class _Locations:
    def __init__(self, locations: list[Location]) -> None:
        self._locations = locations

    def list_all(self) -> tuple[Location, ...]:
        return tuple(self._locations)

    def get(self, location_id: str) -> Location | None:
        return next((l for l in self._locations if l.location_id == location_id), None)


def test_a_phone_an_admin_had_from_before_is_free_for_an_executive(api):
    admin = api.user("admin-1", UserRole.ADMIN)
    location = api.services.location_service.create_location("Chennai", "+914400000001")
    old_admin = _admin_from_before(api, location.location_id)

    taken = api.client.post(
        "/api/v1/admin/users",
        json={
            "email": "exec@example.com",
            "password": "a-long-password",
            "role": "ICR",
            "dial_target": "+919800000009",
        },
        headers=admin,
    )
    assert taken.status_code == 201
    assert taken.json()["dial_target"] == "+919800000009"

    # Made an executive later, the old admin does not get the phone back.
    moved = api.client.patch(
        f"/api/v1/admin/users/{old_admin.user_id}", json={"role": "ICR"}, headers=admin
    ).json()
    assert (moved["role"], moved["location_id"], moved["dial_target"]) == ("ICR", None, None)


def test_admins_are_not_offered_as_executives(api):
    admin = api.user("admin-1", UserRole.ADMIN)
    api.user("icr-1", UserRole.ICR)
    api.user("sup-1", UserRole.SUPERVISOR)
    api.user("mgmt-1", UserRole.MANAGEMENT)

    directory = api.client.get("/api/v1/call-directory", headers=admin).json()

    assert {entry["id"] for entry in directory["executives"]} == {"icr-1", "sup-1"}


def test_a_call_an_admin_took_in_the_past_stays_theirs_in_the_list(api):
    admin = api.user("admin-1", UserRole.ADMIN)
    # As calls were stored when an admin could still take them.
    api.services.call_service.start_call("old-call", time.time() - 60, executive_user_id="admin-1")
    api.services.call_service.end_call("old-call", time.time())

    (listed,) = api.client.get(
        "/api/v1/calls", params={"executive_user_id": "admin-1"}, headers=admin
    ).json()["items"]

    assert (listed["call_id"], listed["executive_name"]) == ("old-call", "admin-1@example.com")
