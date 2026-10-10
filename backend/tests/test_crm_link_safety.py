"""The CRM link when the data or the people are imperfect: a customer file
with a bad row, a file edited while the app runs, a customer set by hand,
and a lookup overtaken by a correction."""

import json
import logging
import os
import time

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.production_checks import configuration_problems
from app.crm.json_file_directory import RELOAD_CHECK_SECONDS, JsonFileCustomerDirectory
from app.domain.customer_contact import ConsentStatus
from app.domain.user import User, UserRole
from app.security.jwt import create_access_token
from app.services.call_customer_repository import InMemoryCallCustomerRepository
from app.services.call_customer_service import CallCustomerService
from tests.test_call_customer import CRM, build_client

_writes = 0


def _customer(customer_id: str, phone: str, **extra) -> dict:
    return {"customer_id": customer_id, "name": f"Customer {customer_id}", "phone_number": phone, **extra}


def _write(path, customers) -> None:
    global _writes
    path.write_text(json.dumps({"customers": customers}), encoding="utf-8")
    # A later write always changes the file's stamp, whatever the clock's resolution.
    _writes += 1
    stamp = time.time_ns() + _writes * 1_000_000_000
    os.utime(path, ns=(stamp, stamp))


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


# ---- A customer file with bad rows ----

def test_one_invalid_customer_does_not_take_the_others_down(tmp_path, caplog):
    path = tmp_path / "crm.json"
    _write(path, [_customer("A", "9845000001"), {"customer_id": "broken"}, _customer("C", "9845000003")])

    with caplog.at_level(logging.WARNING):
        directory = JsonFileCustomerDirectory(path, "91")

    assert directory.customer_count == 2
    assert directory.find_by_phone("+919845000003").customer_id == "C"
    assert len(directory.problems) == 1
    assert "index 1" in directory.problems[0]
    assert "index 1" in caplog.text


def test_a_shared_phone_number_matches_nobody_automatically(tmp_path):
    path = tmp_path / "crm.json"
    _write(
        path,
        [_customer("A", "9845000001"), _customer("B", "+91 98450 00001"), _customer("C", "9845000003")],
    )

    directory = JsonFileCustomerDirectory(path, "91")

    # Both customers exist; the caller could be either, so the agent says who.
    assert directory.find_by_phone("+919845000001") is None
    assert directory.get_customer("A") is not None
    assert directory.get_customer("B") is not None
    assert directory.find_by_phone("+919845000003").customer_id == "C"
    assert "shares a phone number" in directory.problems[0]
    # Never the number itself in what gets logged.
    assert "9845000001" not in directory.problems[0]


def test_a_customer_with_a_duplicate_vehicle_is_skipped_whole(tmp_path):
    vehicle = {"vehicle_id": "V-1", "registration_number": "TN01A1", "make": "Maruti", "model": "Swift"}
    path = tmp_path / "crm.json"
    _write(
        path,
        [_customer("A", "9845000001", vehicles=[vehicle]), _customer("B", "9845000002", vehicles=[vehicle])],
    )

    directory = JsonFileCustomerDirectory(path, "91")

    assert directory.get_customer("B") is None
    assert directory.find_by_phone("+919845000002") is None
    assert [v.customer_id for v in directory.list_vehicles("A")] == ["A"]


# ---- A file edited while the app runs ----

def test_an_edited_file_is_read_again(tmp_path):
    path = tmp_path / "crm.json"
    _write(path, [_customer("A", "9845000001", consent_status="granted")])
    clock = _Clock()
    directory = JsonFileCustomerDirectory(path, "91", clock=clock)

    _write(path, [_customer("A", "9845000001", consent_status="revoked"), _customer("B", "9845000002")])
    # Not checked on every lookup.
    assert directory.get_customer("A").consent_status is ConsentStatus.GRANTED

    clock.now += RELOAD_CHECK_SECONDS + 1

    assert directory.get_customer("A").consent_status is ConsentStatus.REVOKED
    assert directory.find_by_phone("+919845000002").customer_id == "B"


def test_a_file_that_becomes_unreadable_keeps_the_old_customers(tmp_path, caplog):
    path = tmp_path / "crm.json"
    _write(path, [_customer("A", "9845000001")])
    clock = _Clock()
    directory = JsonFileCustomerDirectory(path, "91", clock=clock)

    path.write_text('{"customers": [', encoding="utf-8")  # caught half-written
    clock.now += RELOAD_CHECK_SECONDS + 1
    with caplog.at_level(logging.ERROR):
        assert directory.get_customer("A") is not None
        clock.now += RELOAD_CHECK_SECONDS + 1
        assert directory.get_customer("A") is not None
    assert caplog.text.count("could not be read") == 1  # reported once

    _write(path, [_customer("B", "9845000002")])
    clock.now += RELOAD_CHECK_SECONDS + 1
    assert directory.get_customer("A") is None
    assert directory.get_customer("B") is not None


def test_production_refuses_a_customer_file_that_is_not_there(tmp_path):
    def problems(**values) -> str:
        return "\n".join(configuration_problems(Settings(_env_file=None, **values)))  # type: ignore[call-arg]

    path = tmp_path / "crm.json"
    _write(path, [_customer("A", "9845000001")])

    assert "CRM_JSON_PATH" in problems(crm_provider="json_file")
    assert "CRM_JSON_PATH" in problems(
        crm_provider="json_file", crm_json_path=str(tmp_path / "missing.json")
    )
    assert "CRM_JSON_PATH" not in problems(crm_provider="json_file", crm_json_path=str(path))
    assert "CRM_JSON_PATH" not in problems(crm_provider="none")


# ---- A lookup overtaken by a correction ----

def _crm_file(tmp_path):
    path = tmp_path / "crm.json"
    path.write_text(json.dumps(CRM), encoding="utf-8")
    return path


class _SlowDirectory(JsonFileCustomerDirectory):
    """Runs during_lookup while the CRM is being asked, once."""

    during_lookup = None

    def list_vehicles(self, customer_id):
        if self.during_lookup is not None:
            action, self.during_lookup = self.during_lookup, None
            action()
        return super().list_vehicles(customer_id)


def test_a_number_corrected_during_a_lookup_is_not_undone(tmp_path):
    directory = _SlowDirectory(_crm_file(tmp_path), "91")
    repository = InMemoryCallCustomerRepository()
    service = CallCustomerService(repository, directory, "91")
    service.record_caller("call-1", "9845000001")  # C-1

    directory.during_lookup = lambda: service.identify("call-1", "9845000002")  # C-2
    service.get("call-1")

    assert repository.get("call-1").caller_number == "+919845000002"
    assert service.get("call-1").customer.customer_id == "C-2"


class _CountingDirectory(JsonFileCustomerDirectory):
    lookups = 0

    def list_vehicles(self, customer_id):
        self.lookups += 1
        return super().list_vehicles(customer_id)


def test_the_vehicle_model_is_remembered_for_thirty_seconds(tmp_path):
    directory = _CountingDirectory(_crm_file(tmp_path), "91")
    clock = _Clock()
    service = CallCustomerService(InMemoryCallCustomerRepository(), directory, "91", clock=clock)
    service.record_caller("call-1", "9845000001")

    first = service.resolve_vehicle_model("call-1")
    for _ in range(20):
        assert service.resolve_vehicle_model("call-1") == first
    assert first == "Maruti Suzuki Swift"
    assert directory.lookups == 1

    clock.now += 31
    service.resolve_vehicle_model("call-1")
    assert directory.lookups == 2


def test_changing_the_customer_forgets_the_remembered_model(tmp_path):
    directory = _CountingDirectory(_crm_file(tmp_path), "91")
    service = CallCustomerService(InMemoryCallCustomerRepository(), directory, "91", clock=_Clock())
    service.record_caller("call-1", "9845000001")
    assert service.resolve_vehicle_model("call-1") == "Maruti Suzuki Swift"

    service.identify("call-1", "9845000002")  # two vehicles, none chosen yet

    assert service.resolve_vehicle_model("call-1") is None


# ---- A customer set by hand ----

def test_setting_the_customer_by_hand_is_logged_without_the_number(tmp_path, caplog):
    service = CallCustomerService(
        InMemoryCallCustomerRepository(), JsonFileCustomerDirectory(_crm_file(tmp_path), "91"), "91"
    )
    service.record_caller("call-1", "9845000001")
    service.get("call-1")

    with caplog.at_level(logging.INFO):
        service.identify("call-1", "9845000002", changed_by="icr-7")

    assert "'icr-7'" in caplog.text
    assert "'C-1' -> 'C-2'" in caplog.text
    assert "...0001 -> ...0002" in caplog.text
    assert "9845000002" not in caplog.text


def _client_as(client: TestClient, services, role: UserRole) -> TestClient:
    user = User(
        user_id=f"{role.value.lower()}-9",
        email=f"{role.value.lower()}9@example.com",
        password_hash="unused",
        role=role,
        is_active=True,
        created_at=time.time(),
    )
    services.user_repository.save(user)
    return TestClient(client.app, headers={"Authorization": f"Bearer {create_access_token(user)}"})


def test_only_a_supervisor_changes_the_customer_of_a_completed_call(tmp_path):
    icr, services, _ = build_client(_crm_file(tmp_path))
    icr.post("/api/v1/calls", json={"call_id": "m-1"})

    # During the call, its ICR identifies the caller.
    assert icr.put("/api/v1/calls/m-1/customer", json={"phone_number": "9845000001"}).status_code == 200
    assert icr.post("/api/v1/calls/m-1/complete", json={"end_time": 30.0}).status_code == 200

    refused = icr.put("/api/v1/calls/m-1/customer", json={"phone_number": "9845000002"})
    assert refused.status_code == 403
    assert icr.get("/api/v1/calls/m-1/customer").json()["customer"]["customer_id"] == "C-1"

    supervisor = _client_as(icr, services, UserRole.SUPERVISOR)
    corrected = supervisor.put("/api/v1/calls/m-1/customer", json={"phone_number": "9845000002"})
    assert corrected.status_code == 200
    assert corrected.json()["customer"]["customer_id"] == "C-2"
