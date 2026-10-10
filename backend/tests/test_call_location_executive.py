"""Location, executive and direction on every call: the locations list, the
users' own fields, how each kind of call gets its values, Plivo's dial
callback, who speaks on which track, and the call list filters."""

import re
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
)
from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.core.config import Settings
from app.domain.conversation import CallDirection, Conversation
from app.domain.location import InMemoryLocationRepository, Location
from app.domain.phone_number import normalize_dial_target
from app.domain.user import User, UserRole
from app.domain.user_repository import InMemoryUserRepository
from app.domain.utterance import SpeakerRole
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import build_session_factory
from app.infrastructure.database.repositories.call_listing_query import (
    PostgresCallListingQuery,
)
from app.infrastructure.database.repositories.conversation_repository import (
    PostgresConversationRepository,
)
from app.infrastructure.database.repositories.location_repository import (
    PostgresLocationRepository,
)
from app.infrastructure.database.repositories.user_repository import PostgresUserRepository
from app.security.jwt import create_access_token
from app.services.auth_service import AuthService
from app.services.call_listing import CallListFilters
from app.services.call_routing_service import CallRoute, CallRoutingService
from app.services.call_service import CallService
from app.services.conversation_service import ConversationService
from app.services.in_memory_conversation_repository import InMemoryConversationRepository
from app.services.location_service import LocationError, LocationService
from app.services.telephony_call_mapping_repository import (
    InMemoryTelephonyCallMappingRepository,
)
from app.services.telephony_call_service import TelephonyCallService
from app.services.user_management_service import (
    UNCHANGED,
    UserManagementError,
    UserManagementService,
)
from app.telephony.plivo.provider import PlivoTelephonyProvider
from app.telephony.provider import DialAnswerEvent, DialPlan, InboundCallEvent, track_roles

CHENNAI_LINE = "+914440000001"
MADURAI_LINE = "+914520000002"
CUSTOMER = "+919000000001"
ANSWER = "/api/v1/telephony/plivo/answer"
DIAL = "/api/v1/telephony/plivo/dial"


def _user(user_id: str, role: UserRole = UserRole.ICR, **fields) -> User:
    return User(
        user_id=user_id,
        email=f"{user_id}@example.com",
        password_hash="hash",
        role=role,
        is_active=fields.pop("is_active", True),
        created_at=time.time(),
        **fields,
    )


def _location(location_id: str, name: str, number: str, is_active: bool = True) -> Location:
    return Location(location_id, name, number, is_active, created_at=time.time())


class _Directory:
    """Two locations; Asha and Ravi answer in Chennai, Meena in Madurai."""

    def __init__(self) -> None:
        self.locations = InMemoryLocationRepository()
        self.users = InMemoryUserRepository()
        self.locations.save(_location("chennai", "Chennai", CHENNAI_LINE))
        self.locations.save(_location("madurai", "Madurai", MADURAI_LINE))
        self.users.save(
            _user("asha", display_name="Asha", location_id="chennai", dial_target="+919800000001")
        )
        self.users.save(
            _user("ravi", location_id="chennai", dial_target="sip:ravi@phone.plivo.com")
        )
        self.users.save(_user("meena", location_id="madurai", dial_target="+919800000003"))
        self.routing = CallRoutingService(self.locations, self.users, default_country_code="91")


# ---- Dial targets ----

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+91 98000 00001", "+919800000001"),
        ("9800000001", "+919800000001"),
        ("919800000001", "+919800000001"),
        ("SIP:Ravi@Phone.Plivo.com", "sip:ravi@phone.plivo.com"),
        ("sip:ravi", None),
        ("sip:@host", None),
        ("abc", None),
        (None, None),
    ],
)
def test_dial_targets_are_kept_in_one_form(raw, expected):
    assert normalize_dial_target(raw, "91") == expected


# ---- Locations ----

def _location_service(users=None) -> LocationService:
    return LocationService(InMemoryLocationRepository(), users, default_country_code="91")


def test_a_location_keeps_its_number_in_one_form():
    service = _location_service()

    location = service.create_location("  Chennai   Central ", "044 4000 0001 0"[:13])

    assert location.name == "Chennai Central"
    assert location.phone_number.startswith("+")
    assert location.is_active is True
    assert service.list_locations() == (location,)


def test_two_locations_cannot_share_a_name_or_a_number():
    service = _location_service()
    service.create_location("Chennai", CHENNAI_LINE)

    with pytest.raises(LocationError, match="already a location"):
        service.create_location("chennai", MADURAI_LINE)
    with pytest.raises(LocationError, match="already the number"):
        service.create_location("Madurai", CHENNAI_LINE)
    with pytest.raises(LocationError, match="country code"):
        service.create_location("Madurai", "12")


def test_a_location_can_be_renamed_and_deactivated_but_keeps_its_id():
    service = _location_service()
    location = service.create_location("Chennai", CHENNAI_LINE)

    renamed = service.update_location(location.location_id, name="Chennai South")
    closed = service.update_location(location.location_id, is_active=False)

    assert renamed.name == "Chennai South"
    assert renamed.phone_number == CHENNAI_LINE
    assert closed.is_active is False
    assert closed.location_id == location.location_id
    # Its own name and number are not a clash with itself.
    service.update_location(location.location_id, name="Chennai South", phone_number=CHENNAI_LINE)


def test_a_location_cannot_take_a_users_own_number():
    directory = _Directory()
    service = LocationService(directory.locations, directory.users, default_country_code="91")

    with pytest.raises(LocationError, match="user's own number"):
        service.create_location("Trichy", "+919800000001")


# ---- Users ----

def _user_management(directory: _Directory) -> UserManagementService:
    return UserManagementService(
        directory.users,
        AuthService(directory.users),
        locations=directory.locations,
        default_country_code="91",
    )


def test_a_user_is_created_with_a_name_location_and_dial_target():
    directory = _Directory()

    user = _user_management(directory).create_user(
        "New@Example.com",
        "password-1",
        UserRole.ICR,
        display_name="  Kavya  R ",
        location_id="madurai",
        dial_target="98000 00009",
    )

    stored = directory.users.get_by_id(user.user_id)
    assert stored is not None
    assert (stored.display_name, stored.location_id, stored.dial_target) == (
        "Kavya R",
        "madurai",
        "+919800000009",
    )
    assert stored.name == "Kavya R"


def test_a_bad_value_leaves_no_user_behind():
    directory = _Directory()
    service = _user_management(directory)

    with pytest.raises(UserManagementError, match="location does not exist"):
        service.create_user("new@example.com", "password-1", UserRole.ICR, location_id="nowhere")
    with pytest.raises(UserManagementError, match="already the dial target"):
        service.create_user(
            "new@example.com", "password-1", UserRole.ICR, dial_target="+919800000001"
        )
    with pytest.raises(UserManagementError, match="customers dial"):
        service.create_user("new@example.com", "password-1", UserRole.ICR, dial_target=CHENNAI_LINE)
    with pytest.raises(UserManagementError, match="SIP address"):
        service.create_user("new@example.com", "password-1", UserRole.ICR, dial_target="nonsense")

    assert directory.users.get_by_email("new@example.com") is None


def test_updating_a_user_changes_only_what_is_sent():
    directory = _Directory()
    service = _user_management(directory)
    admin = _user("admin", UserRole.ADMIN)
    directory.users.save(admin)

    moved = service.update_user("asha", admin, location_id="madurai")
    assert (moved.display_name, moved.location_id, moved.dial_target) == (
        "Asha",
        "madurai",
        "+919800000001",
    )

    cleared = service.update_user("asha", admin, dial_target=None, display_name="")
    assert (cleared.display_name, cleared.location_id, cleared.dial_target) == (
        None,
        "madurai",
        None,
    )
    assert cleared.name == "asha@example.com"

    untouched = service.update_user("asha", admin, role=UserRole.SUPERVISOR)
    assert untouched.location_id == "madurai"
    # Keeping one's own dial target is not a clash with oneself.
    service.update_user("ravi", admin, dial_target="sip:ravi@phone.plivo.com")
    assert UNCHANGED is not None


# ---- Routing a phone call ----

def test_an_incoming_call_belongs_to_the_location_dialled_and_rings_its_executives():
    directory = _Directory()

    route = directory.routing.route(CUSTOMER, "914440000001")

    assert route.direction is CallDirection.INBOUND
    assert route.location_id == "chennai"
    assert route.executive_user_id is None
    assert route.customer_number == CUSTOMER
    assert set(route.dial_targets) == {"+919800000001", "sip:ravi@phone.plivo.com"}
    assert route.caller_id is None


def test_inactive_executives_are_not_rung():
    directory = _Directory()
    directory.users.save(
        _user("ravi", location_id="chennai", dial_target="sip:ravi@phone.plivo.com", is_active=False)
    )

    assert directory.routing.route(CUSTOMER, CHENNAI_LINE).dial_targets == ("+919800000001",)


def test_a_call_to_an_unknown_or_closed_number_has_no_location(caplog):
    directory = _Directory()
    directory.locations.save(_location("madurai", "Madurai", MADURAI_LINE, is_active=False))

    unknown = directory.routing.route(CUSTOMER, "+914400000099")
    closed = directory.routing.route(CUSTOMER, MADURAI_LINE)

    assert unknown == CallRoute(customer_number=CUSTOMER)
    assert closed == CallRoute(customer_number=CUSTOMER)
    assert "no location's number" in caplog.text


def test_no_warning_when_no_locations_are_set_up(caplog):
    routing = CallRoutingService(InMemoryLocationRepository(), InMemoryUserRepository())

    assert routing.route(CUSTOMER, CHENNAI_LINE) == CallRoute(customer_number=CUSTOMER)
    assert caplog.text == ""


def test_a_call_an_executive_places_is_an_outgoing_call_of_theirs():
    directory = _Directory()

    route = directory.routing.route("sip:Ravi@phone.plivo.com", "9000000001")

    assert route.direction is CallDirection.OUTBOUND
    assert route.location_id == "chennai"
    assert route.executive_user_id == "ravi"
    assert route.customer_number == "9000000001"
    # The customer is rung, and sees the location's number.
    assert route.dial_targets == ("+919000000001",)
    assert route.caller_id == CHENNAI_LINE


def test_an_executive_calling_a_location_line_is_an_incoming_call():
    directory = _Directory()

    route = directory.routing.route("+919800000001", MADURAI_LINE)

    assert route.direction is CallDirection.INBOUND
    assert route.location_id == "madurai"
    assert route.executive_user_id is None


# ---- The call service ----

def _telephony(directory: _Directory) -> tuple[CallService, TelephonyCallService]:
    call_service = CallService(ConversationService(InMemoryConversationRepository()))
    return call_service, TelephonyCallService(
        call_service, InMemoryTelephonyCallMappingRepository(), call_routing=directory.routing
    )


def _start(telephony: TelephonyCallService, uuid: str, from_number: str, to_number: str) -> str:
    event = InboundCallEvent(uuid, from_number, to_number)
    return telephony.start_call_from_provider("plivo", event, telephony.route_call(event))


def test_whoever_answers_an_incoming_call_becomes_its_executive():
    directory = _Directory()
    call_service, telephony = _telephony(directory)
    call_id = _start(telephony, "uuid-1", CUSTOMER, CHENNAI_LINE)

    before = call_service.get_call(call_id)
    assert (before.direction, before.location_id, before.executive_user_id) == (
        CallDirection.INBOUND,
        "chennai",
        None,
    )

    assert telephony.executive_answered(DialAnswerEvent("uuid-1", "sip:ravi@phone.plivo.com"))
    # Plivo repeats its callbacks: the same answer again changes nothing.
    assert telephony.executive_answered(DialAnswerEvent("uuid-1", "sip:ravi@phone.plivo.com"))

    after = call_service.get_call(call_id)
    assert (after.location_id, after.executive_user_id) == ("chennai", "ravi")


def test_an_answer_fills_in_a_location_the_number_did_not_give():
    directory = _Directory()
    call_service, telephony = _telephony(directory)
    call_id = _start(telephony, "uuid-1", CUSTOMER, "+914400000099")

    telephony.executive_answered(DialAnswerEvent("uuid-1", "919800000003"))

    call = call_service.get_call(call_id)
    assert (call.location_id, call.executive_user_id) == ("madurai", "meena")


def test_an_answer_from_an_unknown_phone_or_call_changes_nothing(caplog):
    directory = _Directory()
    call_service, telephony = _telephony(directory)
    call_id = _start(telephony, "uuid-1", CUSTOMER, CHENNAI_LINE)

    assert telephony.executive_answered(DialAnswerEvent("uuid-1", "+919811111111")) is False
    assert telephony.executive_answered(DialAnswerEvent("no-such-call", "+919800000001")) is False

    assert call_service.get_call(call_id).executive_user_id is None
    assert "no active user's dial target" in caplog.text


def test_an_outgoing_call_keeps_its_executive_when_the_customer_answers():
    directory = _Directory()
    call_service, telephony = _telephony(directory)
    call_id = _start(telephony, "uuid-1", "+919800000001", CUSTOMER)

    # The customer happens to be an executive's number too: still the customer.
    assert telephony.executive_answered(DialAnswerEvent("uuid-1", "+919800000003")) is False

    call = call_service.get_call(call_id)
    assert (call.direction, call.location_id, call.executive_user_id) == (
        CallDirection.OUTBOUND,
        "chennai",
        "asha",
    )


def test_the_executive_can_be_recorded_after_the_call_has_ended():
    directory = _Directory()
    call_service, telephony = _telephony(directory)
    call_id = _start(telephony, "uuid-1", CUSTOMER, CHENNAI_LINE)
    call_service.end_call(call_id, time.time() + 5)

    assert telephony.executive_answered(DialAnswerEvent("uuid-1", "+919800000001"))

    assert call_service.get_call(call_id).executive_user_id == "asha"


def test_a_call_started_without_a_route_is_an_incoming_call_with_nothing_recorded():
    call_service = CallService(ConversationService(InMemoryConversationRepository()))
    telephony = TelephonyCallService(call_service, InMemoryTelephonyCallMappingRepository())
    event = InboundCallEvent("uuid-1", CUSTOMER, CHENNAI_LINE)

    call = call_service.get_call(
        telephony.start_call_from_provider("plivo", event, telephony.route_call(event))
    )

    assert (call.direction, call.location_id, call.executive_user_id) == (
        CallDirection.INBOUND,
        None,
        None,
    )


# ---- Who speaks on which track ----

def test_the_caller_is_the_customer_unless_the_executive_placed_the_call():
    assert track_roles(CallDirection.INBOUND) == {
        "inbound": SpeakerRole.CUSTOMER,
        "outbound": SpeakerRole.ICR,
    }
    assert track_roles(None) == track_roles(CallDirection.INBOUND)
    assert track_roles(CallDirection.OUTBOUND) == {
        "inbound": SpeakerRole.ICR,
        "outbound": SpeakerRole.CUSTOMER,
    }


# ---- Plivo ----

def _plivo(**overrides) -> PlivoTelephonyProvider:
    return PlivoTelephonyProvider(
        Settings(_env_file=None, plivo_auth_token="t", **overrides)  # type: ignore[call-arg]
    )


def test_the_dial_plan_decides_who_plivo_rings_and_where_it_reports():
    xml = _plivo(
        plivo_icr_dial_targets="+919899999999", plivo_icr_caller_id="+914400000000"
    ).build_stream_response(
        "wss://x/stream",
        DialPlan(
            targets=("+919800000001", "sip:ravi@phone.plivo.com"),
            caller_id=CHENNAI_LINE,
            callback_url="https://calls.example.com/api/v1/telephony/plivo/dial?a=1&b=2",
        ),
    ).content

    assert "<Number>+919800000001</Number><User>sip:ravi@phone.plivo.com</User>" in xml
    assert "+919899999999" not in xml
    assert f'callerId="{CHENNAI_LINE}"' in xml
    assert (
        'callbackUrl="https://calls.example.com/api/v1/telephony/plivo/dial?a=1&amp;b=2"'
        ' callbackMethod="POST"'
    ) in xml
    assert 'audioTrack="both"' in xml


def test_an_empty_dial_plan_rings_the_configured_targets():
    xml = _plivo(
        plivo_icr_dial_targets="+919899999999", plivo_icr_caller_id="+914400000000"
    ).build_stream_response("wss://x/stream", DialPlan(callback_url="https://c/dial")).content

    assert "<Number>+919899999999</Number>" in xml
    assert 'callerId="+914400000000"' in xml
    assert 'callbackUrl="https://c/dial"' in xml


def test_with_nobody_to_ring_the_caller_alone_is_streamed():
    xml = _plivo().build_stream_response("wss://x/stream", DialPlan(callback_url="https://c")).content

    assert "<Dial" not in xml
    assert 'keepCallAlive="true"' in xml


@pytest.mark.parametrize(
    "params",
    [
        {"DialAction": "answer", "DialALegUUID": "a-leg", "DialBLegTo": "sip:ravi@phone.plivo.com"},
        {"DialBLegStatus": "connected", "CallUUID": "a-leg", "DialBLegTo": "sip:ravi@phone.plivo.com"},
    ],
)
def test_the_dial_callback_says_who_answered(params):
    assert _plivo().parse_dial_answer(params) == DialAnswerEvent(
        "a-leg", "sip:ravi@phone.plivo.com"
    )


def test_other_stages_of_the_ringing_are_not_an_answer():
    provider = _plivo()

    assert provider.parse_dial_answer({"DialAction": "hangup", "DialALegUUID": "a"}) is None
    assert provider.parse_dial_answer({"DialAction": "digits", "DialALegUUID": "a"}) is None
    assert provider.parse_dial_answer({}) is None


# ---- The API ----

class _NoComplaints(ComplaintDetectionProvider):
    def detect(self, conversation):
        return []


class _Neutral(SentimentAnalysisProvider):
    def analyze(self, conversation):
        return SentimentResult(label=SentimentLabel.NEUTRAL, confidence=0.9)


class _NoQuestions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


def _api(**settings) -> tuple[TestClient, object]:
    services = build_api_services(
        _NoComplaints(),
        _Neutral(),
        _NoQuestions(),
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            telephony_provider="plivo",
            plivo_auth_token="t",
            plivo_validate_signatures=settings.pop("validate", False),
            plivo_stream_base_url="wss://voice.example.com",
            plivo_public_base_url="https://calls.example.com",
            **settings,
        ),
    )
    return TestClient(create_app(services)), services


def _sign_in(client: TestClient, services, user: User) -> dict[str, str]:
    services.user_repository.save(user)
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def _call_id(xml: str) -> str:
    match = re.search(r"/api/v1/calls/([^/]+)/telephony-stream", xml)
    assert match is not None
    return match.group(1)


def _set_up_chennai(client: TestClient, admin: dict[str, str]) -> tuple[str, str]:
    """A location and an executive who answers there; their ids."""
    location = client.post(
        "/api/v1/admin/locations",
        json={"name": "Chennai", "phone_number": CHENNAI_LINE},
        headers=admin,
    )
    assert location.status_code == 201
    location_id = location.json()["location_id"]
    user = client.post(
        "/api/v1/admin/users",
        json={
            "email": "asha@example.com",
            "password": "password-1",
            "role": "ICR",
            "display_name": "Asha",
            "location_id": location_id,
            "dial_target": "+919800000001",
        },
        headers=admin,
    )
    assert user.status_code == 201
    assert user.json()["dial_target"] == "+919800000001"
    return location_id, user.json()["user_id"]


def test_admins_manage_locations_and_others_cannot():
    client, services = _api()
    admin = _sign_in(client, services, _user("admin", UserRole.ADMIN))
    supervisor = _sign_in(client, services, _user("sup", UserRole.SUPERVISOR))

    created = client.post(
        "/api/v1/admin/locations",
        json={"name": "Chennai", "phone_number": "044 4000 0001"},
        headers=admin,
    )
    assert created.status_code == 201
    location_id = created.json()["location_id"]

    duplicate = client.post(
        "/api/v1/admin/locations",
        json={"name": "Chennai", "phone_number": MADURAI_LINE},
        headers=admin,
    )
    assert duplicate.status_code == 409
    assert "already a location" in duplicate.json()["detail"]

    closed = client.patch(
        f"/api/v1/admin/locations/{location_id}", json={"is_active": False}, headers=admin
    )
    assert closed.json()["is_active"] is False
    assert [l["name"] for l in client.get("/api/v1/admin/locations", headers=admin).json()] == [
        "Chennai"
    ]
    assert (
        client.patch("/api/v1/admin/locations/nowhere", json={"name": "X"}, headers=admin).status_code
        == 404
    )

    assert client.get("/api/v1/admin/locations", headers=supervisor).status_code == 403
    assert (
        client.post(
            "/api/v1/admin/locations",
            json={"name": "Madurai", "phone_number": MADURAI_LINE},
            headers=supervisor,
        ).status_code
        == 403
    )
    assert client.get("/api/v1/admin/locations").status_code == 401


def test_a_user_update_leaves_out_fields_or_clears_them():
    client, services = _api()
    admin = _sign_in(client, services, _user("admin", UserRole.ADMIN))
    location_id, user_id = _set_up_chennai(client, admin)

    kept = client.patch(
        f"/api/v1/admin/users/{user_id}", json={"role": "SUPERVISOR"}, headers=admin
    ).json()
    assert (kept["display_name"], kept["location_id"], kept["dial_target"]) == (
        "Asha",
        location_id,
        "+919800000001",
    )

    cleared = client.patch(
        f"/api/v1/admin/users/{user_id}", json={"dial_target": None}, headers=admin
    ).json()
    assert cleared["dial_target"] is None
    assert cleared["location_id"] == location_id

    bad = client.patch(
        f"/api/v1/admin/users/{user_id}", json={"location_id": "nowhere"}, headers=admin
    )
    assert bad.status_code == 409


def test_a_manual_call_is_taken_by_whoever_is_signed_in():
    client, services = _api()
    admin = _sign_in(client, services, _user("admin", UserRole.ADMIN))
    location_id, _ = _set_up_chennai(client, admin)
    asha = services.user_repository.get_by_email("asha@example.com")
    headers = {"Authorization": f"Bearer {create_access_token(asha)}"}

    incoming = client.post("/api/v1/calls", json={"call_id": "manual-1"}, headers=headers).json()
    outgoing = client.post(
        "/api/v1/calls", json={"call_id": "manual-2", "direction": "outbound"}, headers=headers
    ).json()

    assert (incoming["direction"], incoming["location_id"], incoming["executive_user_id"]) == (
        "inbound",
        location_id,
        asha.user_id,
    )
    assert outgoing["direction"] == "outbound"


def test_a_plivo_call_gets_its_location_from_the_number_and_its_executive_from_the_answer():
    client, services = _api()
    admin = _sign_in(client, services, _user("admin", UserRole.ADMIN))
    location_id, user_id = _set_up_chennai(client, admin)

    answer = client.post(
        ANSWER, data={"CallUUID": "uuid-1", "From": "919000000001", "To": "914440000001"}
    )

    assert answer.status_code == 200
    assert "<Number>+919800000001</Number>" in answer.text
    assert '/api/v1/telephony/plivo/dial" callbackMethod="POST"' in answer.text
    call_id = _call_id(answer.text)
    call = client.get(f"/api/v1/calls/{call_id}", headers=admin).json()
    assert (call["direction"], call["location_id"], call["executive_user_id"]) == (
        "inbound",
        location_id,
        None,
    )

    ringing = client.post(DIAL, data={"DialAction": "hangup", "DialALegUUID": "uuid-1"})
    picked_up = client.post(
        DIAL,
        data={"DialAction": "answer", "DialALegUUID": "uuid-1", "DialBLegTo": "919800000001"},
    )

    assert ringing.status_code == picked_up.status_code == 200
    call = client.get(f"/api/v1/calls/{call_id}", headers=admin).json()
    assert call["executive_user_id"] == user_id

    listed = client.get("/api/v1/calls", headers=admin).json()["items"][0]
    assert (listed["location_name"], listed["executive_name"], listed["direction"]) == (
        "Chennai",
        "Asha",
        "inbound",
    )
    assert listed["caller_number"] == "+919000000001"


def test_a_call_an_executive_places_through_plivo_rings_the_customer():
    client, services = _api()
    admin = _sign_in(client, services, _user("admin", UserRole.ADMIN))
    location_id, user_id = _set_up_chennai(client, admin)

    answer = client.post(
        ANSWER, data={"CallUUID": "uuid-2", "From": "919800000001", "To": "919000000001"}
    )

    assert f'callerId="{CHENNAI_LINE}"' in answer.text
    assert "<Number>+919000000001</Number>" in answer.text
    call = client.get(f"/api/v1/calls/{_call_id(answer.text)}", headers=admin).json()
    assert (call["direction"], call["location_id"], call["executive_user_id"]) == (
        "outbound",
        location_id,
        user_id,
    )
    listed = client.get("/api/v1/calls", headers=admin).json()["items"][0]
    # The customer is the number dialled, not the executive's own.
    assert listed["caller_number"] == "+919000000001"


def test_the_dial_callback_is_signature_checked_and_survives_bad_input():
    client, _ = _api(validate=True)
    assert client.post(DIAL, data={"DialAction": "answer"}).status_code == 403

    client, _ = _api()
    assert client.post(DIAL, data={"DialAction": "answer"}).status_code == 422
    # An answer for a call we do not have is accepted and ignored.
    unknown = client.post(
        DIAL, data={"DialAction": "answer", "DialALegUUID": "nope", "DialBLegTo": "+919800000001"}
    )
    assert unknown.status_code == 200


def test_a_test_call_is_taken_by_whoever_replays_it():
    client, services = _api()
    supervisor = _user("sup", UserRole.SUPERVISOR, location_id="somewhere")
    headers = _sign_in(client, services, supervisor)

    started = client.post("/api/v1/test-calls", json={"from_number": CUSTOMER}, headers=headers)

    assert started.status_code == 201
    call = client.get(f"/api/v1/calls/{started.json()['call_id']}", headers=headers).json()
    assert (call["direction"], call["location_id"], call["executive_user_id"]) == (
        "inbound",
        "somewhere",
        "sup",
    )


def test_the_call_list_filters_by_location_executive_and_direction():
    client, services = _api()
    admin = _sign_in(client, services, _user("admin", UserRole.ADMIN))
    location_id, user_id = _set_up_chennai(client, admin)
    asha = {"Authorization": f"Bearer {create_access_token(services.user_repository.get_by_id(user_id))}"}
    client.post("/api/v1/calls", json={"call_id": "by-asha"}, headers=asha)
    client.post("/api/v1/calls", json={"call_id": "by-asha-out", "direction": "outbound"}, headers=asha)
    client.post("/api/v1/calls", json={"call_id": "by-admin"}, headers=admin)

    def ids(**params) -> set[str]:
        page = client.get("/api/v1/calls", params=params, headers=admin).json()
        return {item["call_id"] for item in page["items"]}

    assert ids() == {"by-asha", "by-asha-out", "by-admin"}
    assert ids(location_id=location_id) == {"by-asha", "by-asha-out"}
    assert ids(executive_user_id="admin") == {"by-admin"}
    assert ids(direction="outbound") == {"by-asha-out"}
    assert ids(executive_user_id=user_id, direction="inbound") == {"by-asha"}
    assert ids(location_id="nowhere") == set()
    assert client.get("/api/v1/calls", params={"direction": "sideways"}, headers=admin).status_code == 422


def test_the_call_directory_lists_what_calls_can_be_filtered_by():
    client, services = _api()
    admin = _sign_in(client, services, _user("admin", UserRole.ADMIN))
    location_id, user_id = _set_up_chennai(client, admin)

    directory = client.get("/api/v1/call-directory", headers=admin).json()

    assert directory["locations"] == [{"id": location_id, "name": "Chennai", "is_active": True}]
    assert directory["executives"] == [
        {"id": "admin", "name": "admin@example.com", "is_active": True},
        {"id": user_id, "name": "Asha", "is_active": True},
    ]
    assert client.get("/api/v1/call-directory").status_code == 401


# ---- The database ----

@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield build_session_factory(engine)
    engine.dispose()


def test_locations_and_the_users_fields_are_stored(session_factory):
    locations = PostgresLocationRepository(session_factory)
    users = PostgresUserRepository(session_factory)
    locations.save(_location("madurai", "madurai", MADURAI_LINE))
    locations.save(_location("chennai", "Chennai", CHENNAI_LINE))
    locations.save(_location("madurai", "Madurai", MADURAI_LINE, is_active=False))
    users.save(_user("asha", display_name="Asha", location_id="chennai", dial_target="+919800000001"))
    users.save(_user("plain"))

    assert [l.name for l in locations.list_all()] == ["Chennai", "Madurai"]
    assert locations.get("madurai").is_active is False
    assert locations.get("nowhere") is None
    asha, plain = users.get_by_id("asha"), users.get_by_id("plain")
    assert (asha.display_name, asha.location_id, asha.dial_target) == (
        "Asha",
        "chennai",
        "+919800000001",
    )
    assert (plain.display_name, plain.location_id, plain.dial_target) == (None, None, None)


def test_a_calls_location_executive_and_direction_are_stored_and_updated(session_factory):
    conversations = PostgresConversationRepository(session_factory)
    conversations.add(
        Conversation("call-1", direction=CallDirection.INBOUND, location_id="chennai")
    )
    conversations.add(Conversation("old-call"))

    stored = conversations.get("call-1")
    stored.assign("asha", "madurai")
    conversations.save(stored)

    again = conversations.get("call-1")
    assert (again.direction, again.location_id, again.executive_user_id) == (
        CallDirection.INBOUND,
        "chennai",
        "asha",
    )
    old = conversations.get("old-call")
    assert (old.direction, old.location_id, old.executive_user_id) == (None, None, None)


def test_the_stored_call_list_names_and_filters_location_and_executive(session_factory):
    PostgresLocationRepository(session_factory).save(_location("chennai", "Chennai", CHENNAI_LINE))
    users = PostgresUserRepository(session_factory)
    users.save(_user("asha", display_name="Asha"))
    users.save(_user("ravi"))
    conversations = PostgresConversationRepository(session_factory)
    conversations.add(
        Conversation(
            "c1",
            direction=CallDirection.INBOUND,
            location_id="chennai",
            executive_user_id="asha",
        )
    )
    conversations.add(
        Conversation("c2", direction=CallDirection.OUTBOUND, executive_user_id="ravi")
    )
    conversations.add(Conversation("old"))
    listing = PostgresCallListingQuery(session_factory)

    def search(**filters):
        return {i.call_id: i for i in listing.search(CallListFilters(**filters), 10, 0).items}

    everything = search()
    assert set(everything) == {"c1", "c2", "old"}
    assert (everything["c1"].location_name, everything["c1"].executive_name) == ("Chennai", "Asha")
    assert (everything["c2"].location_name, everything["c2"].executive_name) == (
        None,
        "ravi@example.com",
    )
    assert everything["old"].direction is None
    assert set(search(location_id="chennai")) == {"c1"}
    assert set(search(executive_user_id="ravi")) == {"c2"}
    assert set(search(direction=CallDirection.OUTBOUND)) == {"c2"}
    assert set(search(direction=CallDirection.INBOUND, executive_user_id="ravi")) == set()
