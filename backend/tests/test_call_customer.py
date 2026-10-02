"""Caller identity and the CRM boundary: phone normalisation, the JSON-file
CRM, the call <-> customer link, its API and its use for summary delivery."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.ai.complaint.provider import ComplaintDetectionProvider, ComplaintDetectionResult
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
)
from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.core.config import Settings
from app.crm.json_file_directory import CrmDataError, JsonFileCustomerDirectory
from app.crm.provider import CrmUnavailableError, CustomerDirectory, NoCustomerDirectory
from app.domain.call_customer import CallCustomerLink, CustomerMatchStatus
from app.domain.customer_contact import ConsentStatus, MessagingChannel
from app.domain.customer_summary_delivery import DeliveryStatus
from app.domain.phone_number import normalize_phone_number
from app.domain.user import User, UserRole
from app.security.jwt import create_access_token
from app.services.call_customer_repository import InMemoryCallCustomerRepository
from app.services.call_customer_service import (
    CallCustomerService,
    InvalidPhoneNumberError,
    VehicleSelectionError,
)
from app.services.customer_summary_repository import InMemoryCustomerSummaryDeliveryRepository
from app.telephony.plivo.signature import NONCE_HEADER, SIGNATURE_HEADER, compute_signature

CRM = {
    "customers": [
        {
            "customer_id": "C-1",
            "name": "Asha Raman",
            "phone_number": "+91 98450 00001",
            "preferred_channel": "whatsapp",
            "consent_status": "granted",
            "language": "ta",
            "vehicles": [
                {
                    "vehicle_id": "V-1",
                    "registration_number": "TN09AB1234",
                    "make": "Maruti Suzuki",
                    "model": "Swift",
                    "year": 2021,
                    "service_history": [
                        {
                            "service_id": "S-old",
                            "service_date": "2025-01-10",
                            "description": "First service",
                        },
                        {
                            "service_id": "S-new",
                            "service_date": "2026-08-14",
                            "description": "Brake pads",
                            "odometer_km": 20150,
                        },
                    ],
                }
            ],
        },
        {
            "customer_id": "C-2",
            "name": "Rohit Kulkarni",
            "phone_number": "9845000002",
            "vehicles": [
                {"vehicle_id": "V-2", "registration_number": "MH12CD5678", "make": "Hyundai", "model": "Creta"},
                {"vehicle_id": "V-3", "registration_number": "MH12EF9012", "make": "Tata", "model": "Nexon EV"},
            ],
        },
    ]
}


@pytest.fixture
def crm_file(tmp_path):
    path = tmp_path / "crm.json"
    path.write_text(json.dumps(CRM), encoding="utf-8")
    return path


@pytest.fixture
def directory(crm_file):
    return JsonFileCustomerDirectory(crm_file, default_country_code="91")


def make_service(directory: CustomerDirectory) -> CallCustomerService:
    return CallCustomerService(
        InMemoryCallCustomerRepository(), directory, default_country_code="91"
    )


# ---- Phone numbers ----

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("+91 98450 00001", "+919845000001"),
        ("919845000001", "+919845000001"),
        ("9845000001", "+919845000001"),
        ("09845000001", "+919845000001"),
        ("0091 98450-00001", "+919845000001"),
        ("+1 (415) 555-0100", "+14155550100"),
    ],
)
def test_phone_numbers_are_normalised(raw, expected):
    assert normalize_phone_number(raw, "91") == expected


@pytest.mark.parametrize("raw", [None, "", "anonymous", "Restricted", "12345", "+1234567890123456"])
def test_unusable_numbers_normalise_to_none(raw):
    assert normalize_phone_number(raw, "91") is None


def test_national_number_without_default_country_is_kept_as_is():
    assert normalize_phone_number("9845000001") == "+9845000001"


# ---- JSON-file CRM ----

def test_json_directory_finds_customers_by_any_number_format(directory):
    customer = directory.find_by_phone(normalize_phone_number("98450 00001", "91"))

    assert customer is not None
    assert customer.customer_id == "C-1"
    assert customer.phone_number == "+919845000001"
    assert customer.preferred_channel is MessagingChannel.WHATSAPP
    assert customer.consent_status is ConsentStatus.GRANTED
    assert directory.find_by_phone("+910000000000") is None


def test_json_directory_lists_vehicles_and_history_newest_first(directory):
    (vehicle,) = directory.list_vehicles("C-1")

    assert vehicle.registration_number == "TN09AB1234"
    assert [r.service_id for r in directory.list_service_history("V-1")] == ["S-new", "S-old"]
    assert directory.list_vehicles("missing") == ()


@pytest.mark.parametrize(
    "content, message",
    [
        ("not json", "not valid JSON"),
        ("[]", "'customers' list"),
        (json.dumps({"customers": [{"customer_id": "C-1"}]}), "index 0"),
        (
            json.dumps(
                {
                    "customers": [
                        {"customer_id": "A", "name": "A", "phone_number": "9845000001"},
                        {"customer_id": "B", "name": "B", "phone_number": "+91 98450 00001"},
                    ]
                }
            ),
            "belongs to two customers",
        ),
    ],
)
def test_invalid_crm_files_fail_loudly(tmp_path, content, message):
    path = tmp_path / "crm.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(CrmDataError, match=message):
        JsonFileCustomerDirectory(path, "91")


def test_missing_crm_file_fails_loudly(tmp_path):
    with pytest.raises(CrmDataError, match="Cannot read"):
        JsonFileCustomerDirectory(tmp_path / "missing.json")


def test_sample_crm_file_in_the_repository_is_valid():
    from pathlib import Path

    sample = Path(__file__).resolve().parents[1] / "data" / "crm_sample.json"
    directory = JsonFileCustomerDirectory(sample, "91")

    assert directory.find_by_phone("+919845000001") is not None


# ---- Linking calls to customers ----

def test_recorded_caller_is_matched_and_remembered(directory):
    service = make_service(directory)
    service.record_caller("call-1", "9845000001")

    view = service.get("call-1")

    assert view.status is CustomerMatchStatus.MATCHED
    assert view.caller_number == "+919845000001"
    assert view.customer is not None and view.customer.customer_id == "C-1"
    # A single vehicle is selected automatically, with its history.
    assert view.selected_vehicle_id == "V-1"
    assert [r.service_id for r in view.service_history] == ["S-new", "S-old"]


def test_match_survives_a_phone_number_change_in_the_crm(directory):
    repository = InMemoryCallCustomerRepository()
    service = CallCustomerService(repository, directory, "91")
    service.record_caller("call-1", "9845000001")
    service.get("call-1")
    assert repository.get("call-1").customer_id == "C-1"

    directory._by_phone.clear()  # the customer's number changed in the CRM

    assert service.get("call-1").customer.customer_id == "C-1"


def test_unknown_withheld_and_missing_callers(directory):
    service = make_service(directory)
    service.record_caller("unknown", "+14155550100")
    service.record_caller("withheld", "anonymous")

    assert service.get("unknown").status is CustomerMatchStatus.NOT_FOUND
    assert service.get("withheld").status is CustomerMatchStatus.NO_CALLER_NUMBER
    assert service.get("never-recorded").status is CustomerMatchStatus.NO_CALLER_NUMBER
    assert service.get("withheld").caller_number is None


def test_no_crm_reports_not_configured_but_keeps_the_caller():
    service = make_service(NoCustomerDirectory())
    service.record_caller("call-1", "9845000001")

    view = service.get("call-1")

    assert view.status is CustomerMatchStatus.CRM_NOT_CONFIGURED
    assert view.caller_number == "+919845000001"
    assert service.resolve_contact("call-1") is None


def test_crm_outage_is_reported_as_unavailable_not_as_unknown():
    class DownCrm(NoCustomerDirectory):
        is_configured = True

        def find_by_phone(self, phone_number):
            raise CrmUnavailableError("timeout")

    service = make_service(DownCrm())
    service.record_caller("call-1", "9845000001")

    view = service.get("call-1")

    assert view.status is CustomerMatchStatus.CRM_UNAVAILABLE
    assert view.caller_number == "+919845000001"
    assert service.resolve_contact("call-1") is None


def test_identify_sets_the_number_by_hand_and_rejects_bad_numbers(directory):
    service = make_service(directory)
    service.record_caller("call-1", "anonymous")

    view = service.identify("call-1", "98450 00002")

    assert view.customer is not None and view.customer.customer_id == "C-2"
    with pytest.raises(InvalidPhoneNumberError):
        service.identify("call-1", "not a number")


def test_vehicle_must_be_chosen_when_the_customer_has_several(directory):
    service = make_service(directory)
    service.record_caller("call-1", "9845000002")
    assert service.get("call-1").selected_vehicle_id is None

    view = service.select_vehicle("call-1", "V-3")

    assert view.selected_vehicle_id == "V-3"
    assert service.get("call-1").selected_vehicle_id == "V-3"
    assert service.select_vehicle("call-1", None).selected_vehicle_id is None


def test_vehicle_selection_is_validated(directory):
    service = make_service(directory)
    service.record_caller("call-1", "9845000002")

    with pytest.raises(VehicleSelectionError, match="does not belong"):
        service.select_vehicle("call-1", "V-1")
    with pytest.raises(VehicleSelectionError, match="identified"):
        service.select_vehicle("nobody", "V-1")


def test_a_new_caller_number_clears_the_previous_match(directory):
    service = make_service(directory)
    service.record_caller("call-1", "9845000002")
    service.select_vehicle("call-1", "V-2")

    view = service.identify("call-1", "9845000001")

    assert view.customer.customer_id == "C-1"
    assert view.selected_vehicle_id == "V-1"


def test_resolve_contact_returns_the_messaging_contact(directory):
    service = make_service(directory)
    service.record_caller("call-1", "9845000001")

    contact = service.resolve_contact("call-1")

    assert contact is not None
    assert contact.customer_id == "C-1"
    assert contact.phone_number == "+919845000001"
    assert contact.preferred_channel is MessagingChannel.WHATSAPP


def test_link_rejects_a_vehicle_without_a_customer():
    with pytest.raises(ValueError, match="together with its customer"):
        CallCustomerLink(call_id="call-1", vehicle_id="V-1")


@pytest.mark.parametrize(
    "changes", [{"customer_name": "Asha Raman"}, {"vehicle_registration": "TN09AB1234"}]
)
def test_link_rejects_a_snapshot_without_a_customer(changes):
    with pytest.raises(ValueError, match="together with its customer"):
        CallCustomerLink(call_id="call-1", **changes)


# ---- Customer name and vehicle snapshot ----

def test_lookup_stores_the_customer_name_and_only_vehicle(directory):
    repository = InMemoryCallCustomerRepository()
    service = CallCustomerService(repository, directory, "91")
    service.record_caller("call-1", "9845000001")
    assert repository.get("call-1").customer_name is None

    service.get("call-1")

    link = repository.get("call-1")
    assert (link.customer_id, link.customer_name, link.vehicle_registration) == (
        "C-1",
        "Asha Raman",
        "TN09AB1234",
    )


def test_snapshot_follows_the_vehicle_choice_and_a_new_caller(directory):
    repository = InMemoryCallCustomerRepository()
    service = CallCustomerService(repository, directory, "91")
    service.record_caller("call-1", "9845000002")
    service.get("call-1")
    # Several vehicles and none chosen: the name is known, the vehicle is not.
    assert repository.get("call-1").customer_name == "Rohit Kulkarni"
    assert repository.get("call-1").vehicle_registration is None

    service.select_vehicle("call-1", "V-3")
    assert repository.get("call-1").vehicle_registration == "MH12EF9012"
    service.select_vehicle("call-1", None)
    assert repository.get("call-1").vehicle_registration is None

    service.record_caller("call-1", "+14155550100")
    link = repository.get("call-1")
    assert (link.customer_name, link.vehicle_registration) == (None, None)


def test_an_unchanged_snapshot_is_not_rewritten(directory):
    repository = InMemoryCallCustomerRepository()
    service = CallCustomerService(repository, directory, "91", clock=lambda: 5.0)
    service.record_caller("call-1", "9845000001")
    service.get("call-1")
    service._clock = lambda: 9.0

    service.get("call-1")

    assert repository.get("call-1").updated_at == 5.0


def test_refresh_customer_names_fills_calls_without_one(directory):
    repository = InMemoryCallCustomerRepository()
    service = CallCustomerService(repository, directory, "91")
    # Stored before names were kept: a customer id but no name.
    repository.save(CallCustomerLink("old", caller_number="+919845000001", customer_id="C-1"))
    repository.save(CallCustomerLink("stranger", caller_number="+14155550100"))
    repository.save(CallCustomerLink("withheld"))

    assert service.refresh_customer_names() == (1, 2)
    assert repository.get("old").customer_name == "Asha Raman"
    assert [link.call_id for link in repository.list_without_customer_name()] == ["stranger"]


# ---- API, through the real composition root ----

class _Complaints(ComplaintDetectionProvider):
    def detect(self, conversation, learning_context=()):
        return [ComplaintDetectionResult("Turnaround Time", 0.9, "The car was late.")]


class _Sentiment(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEGATIVE, 0.8, "Upset about the delay.")


class _Questions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


def build_client(crm_file, **settings_overrides):
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        crm_provider="json_file",
        crm_json_path=str(crm_file),
        plivo_auth_token="test-auth-token",
        **settings_overrides,
    )
    delivery_repository = InMemoryCustomerSummaryDeliveryRepository()
    services = build_api_services(
        _Complaints(),
        _Sentiment(),
        _Questions(),
        settings,
        customer_summary_delivery_repository=delivery_repository,
    )
    app = create_app(services)
    user = User(
        user_id="icr-1",
        email="icr@example.com",
        password_hash="unused",
        role=UserRole.ICR,
        is_active=True,
        created_at=time.time(),
    )
    services.user_repository.save(user)
    client = TestClient(app, headers={"Authorization": f"Bearer {create_access_token(user)}"})
    return client, services, delivery_repository


@pytest.fixture
def api(crm_file):
    client, services, _ = build_client(crm_file)
    return client, services


def test_manual_call_can_start_with_a_caller_number(api):
    client, _ = api

    assert client.post("/api/v1/calls", json={"call_id": "m-1", "caller_number": "98450 00001"}).status_code == 201
    body = client.get("/api/v1/calls/m-1/customer").json()

    assert body["status"] == "matched"
    assert body["caller_number"] == "+919845000001"
    assert body["customer"]["name"] == "Asha Raman"
    assert body["customer"]["preferred_channel"] == "whatsapp"
    assert [v["vehicle_id"] for v in body["vehicles"]] == ["V-1"]
    assert body["selected_vehicle_id"] == "V-1"
    assert body["service_history"][0]["service_id"] == "S-new"


def test_invalid_caller_number_is_rejected_before_the_call_is_created(api):
    client, services = api

    response = client.post("/api/v1/calls", json={"call_id": "m-2", "caller_number": "abc"})

    assert response.status_code == 422
    assert client.get("/api/v1/calls/m-2").status_code == 404


def test_call_without_a_number_can_be_identified_later(api):
    client, _ = api
    client.post("/api/v1/calls", json={"call_id": "m-3"})

    assert client.get("/api/v1/calls/m-3/customer").json()["status"] == "no_caller_number"
    body = client.put("/api/v1/calls/m-3/customer", json={"phone_number": "9845000002"}).json()

    assert body["customer"]["customer_id"] == "C-2"
    assert body["selected_vehicle_id"] is None
    chosen = client.put("/api/v1/calls/m-3/customer/vehicle", json={"vehicle_id": "V-2"})
    assert chosen.status_code == 200
    assert chosen.json()["selected_vehicle_id"] == "V-2"
    assert client.put("/api/v1/calls/m-3/customer/vehicle", json={"vehicle_id": "V-1"}).status_code == 422
    assert client.put("/api/v1/calls/m-3/customer", json={"phone_number": "nope"}).status_code == 422


def test_customer_routes_return_404_for_unknown_calls_and_require_login(api):
    client, _ = api

    assert client.get("/api/v1/calls/missing/customer").status_code == 404
    assert client.put("/api/v1/calls/missing/customer", json={"phone_number": "9845000001"}).status_code == 404
    anonymous = TestClient(client.app)
    assert anonymous.get("/api/v1/calls/missing/customer").status_code == 401


def _answer(client: TestClient, call_uuid: str, from_number: str) -> str:
    url = "http://testserver/api/v1/telephony/plivo/answer"
    response = client.post(
        "/api/v1/telephony/plivo/answer",
        data={"CallUUID": call_uuid, "From": from_number, "To": "+918000000000"},
        headers={
            SIGNATURE_HEADER: compute_signature("test-auth-token", url, "nonce-1"),
            NONCE_HEADER: "nonce-1",
        },
    )
    assert response.status_code == 200
    return response.text.split("/api/v1/calls/")[1].split("/telephony-stream")[0]


def test_telephony_caller_number_is_recorded_and_matched(crm_file):
    client, _, _ = build_client(crm_file, plivo_stream_base_url="wss://voice.example.com")

    call_id = _answer(client, "uuid-1", "919845000001")

    body = client.get(f"/api/v1/calls/{call_id}/customer").json()
    assert body["status"] == "matched"
    assert body["customer"]["customer_id"] == "C-1"


def test_withheld_telephony_caller_still_starts_the_call(crm_file):
    client, _, _ = build_client(crm_file, plivo_stream_base_url="wss://voice.example.com")

    call_id = _answer(client, "uuid-2", "anonymous")

    assert client.get(f"/api/v1/calls/{call_id}").json()["status"] == "active"
    assert client.get(f"/api/v1/calls/{call_id}/customer").json()["status"] == "no_caller_number"


def test_caller_recording_failure_never_blocks_the_phone_call(crm_file, monkeypatch):
    client, services, _ = build_client(crm_file, plivo_stream_base_url="wss://voice.example.com")

    def broken(call_id, raw_number):
        raise RuntimeError("database down")

    monkeypatch.setattr(services.call_customer_service, "record_caller", broken)

    call_id = _answer(client, "uuid-3", "919845000001")

    assert client.get(f"/api/v1/calls/{call_id}").json()["status"] == "active"


def test_identified_customer_receives_the_post_call_summary(crm_file):
    client, _, deliveries = build_client(
        crm_file,
        customer_summary_enabled=True,
        customer_summary_delivery_provider="noop",
    )
    client.post("/api/v1/calls", json={"call_id": "m-4", "caller_number": "9845000001"})
    client.post(
        "/api/v1/calls/m-4/utterances",
        json={
            "utterance_id": "u1",
            "transcript": "My car was supposed to be ready yesterday.",
            "speaker_role": "CUSTOMER",
            "languages": ["en"],
            "start_time": 0.0,
            "end_time": 3.0,
        },
    )

    assert client.post("/api/v1/calls/m-4/complete", json={"end_time": 30.0}).status_code == 200

    (delivery,) = deliveries.get_by_call_id("m-4")
    assert delivery.customer_id == "C-1"
    assert delivery.status is DeliveryStatus.SENT
    assert delivery.channel is MessagingChannel.WHATSAPP


def test_unidentified_caller_gets_no_summary_delivery(crm_file):
    client, _, deliveries = build_client(
        crm_file,
        customer_summary_enabled=True,
        customer_summary_delivery_provider="noop",
    )
    client.post("/api/v1/calls", json={"call_id": "m-5", "caller_number": "+14155550100"})
    client.post(
        "/api/v1/calls/m-5/utterances",
        json={
            "utterance_id": "u1",
            "transcript": "My car was supposed to be ready yesterday.",
            "speaker_role": "CUSTOMER",
            "languages": ["en"],
            "start_time": 0.0,
            "end_time": 3.0,
        },
    )

    client.post("/api/v1/calls/m-5/complete", json={"end_time": 30.0})

    assert deliveries.get_by_call_id("m-5") == ()


# ---- The call list shows and searches the customer ----

def test_call_list_shows_and_searches_customers_and_numbers(api):
    client, _ = api
    for call_id, number in [("asha", "98450 00001"), ("rohit", "9845000002"), ("anon", None)]:
        payload = {"call_id": call_id, **({"caller_number": number} if number else {})}
        client.post("/api/v1/calls", json=payload)
        client.get(f"/api/v1/calls/{call_id}/customer")  # as the Live Call page does
    client.put("/api/v1/calls/rohit/customer/vehicle", json={"vehicle_id": "V-3"})

    def listed(**params):
        items = client.get("/api/v1/calls", params=params).json()["items"]
        return [item["call_id"] for item in items]

    items = client.get("/api/v1/calls").json()["items"]
    asha = next(item for item in items if item["call_id"] == "asha")
    assert (asha["customer_name"], asha["vehicle_registration"], asha["caller_number"]) == (
        "Asha Raman",
        "TN09AB1234",
        "+919845000001",
    )
    assert listed(customer="asha") == ["asha"]
    assert listed(customer="mh12 ef") == ["rohit"]  # registration, spaces ignored
    assert listed(customer="nobody") == []
    assert listed(phone="000002") == ["rohit"]
    assert listed(phone="+91 98450") == ["rohit", "asha"]
