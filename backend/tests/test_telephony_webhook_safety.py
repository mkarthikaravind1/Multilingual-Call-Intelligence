"""The Plivo webhooks against what a real provider does: its actual
signature, a repeated answer webhook, and a hangup that never arrives."""

import base64
import hashlib
import hmac
import logging

from app.domain.conversation import ConversationStatus
from app.domain.utterance import SpeakerRole, Utterance
from app.services.call_service import CallService
from app.services.conversation_service import ConversationService
from app.services.in_memory_conversation_repository import InMemoryConversationRepository
from app.services.stale_call_service import StaleCallSweeper
from app.services.telephony_call_mapping_repository import (
    InMemoryTelephonyCallMappingRepository,
)
from app.services.telephony_call_service import TelephonyCallService
from app.telephony.plivo.signature import (
    NONCE_HEADER,
    SIGNATURE_HEADER,
    signed_message,
    validate_signature,
)
from app.telephony.provider import CallProviderStatus, CallStatusEvent, InboundCallEvent

TOKEN = "test-auth-token"
URL = "https://calls.example.com/api/v1/telephony/plivo/answer"
NONCE = "05429567804466091622"
PARAMS = {"To": "+918000000000", "CallUUID": "abc-123", "From": "+919000000000"}


def _plivo_signs(message: str) -> str:
    """Plivo's side, written out rather than taken from our own helper."""
    digest = hmac.new(TOKEN.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


# ---- Signature (Plivo V3: URL + sorted POST fields + "." + nonce) ----

def test_signed_message_is_the_one_plivo_signs():
    assert signed_message(URL, PARAMS, NONCE) == (
        "https://calls.example.com/api/v1/telephony/plivo/answer?"
        "CallUUIDabc-123From+919000000000To+918000000000"
        ".05429567804466091622"
    )


def test_signed_message_keeps_a_sorted_query_string():
    assert signed_message(URL + "?b=2&a=1", {"CallUUID": "abc"}, NONCE) == (
        "https://calls.example.com/api/v1/telephony/plivo/answer?a=1&b=2.CallUUIDabc"
        ".05429567804466091622"
    )
    assert signed_message(URL, {}, NONCE) == URL + ".05429567804466091622"


def test_a_request_signed_as_plivo_does_is_accepted():
    signature = _plivo_signs(
        URL + "?CallUUIDabc-123From+919000000000To+918000000000." + NONCE
    )
    headers = {SIGNATURE_HEADER: signature, NONCE_HEADER: NONCE}

    assert validate_signature(TOKEN, headers, URL, PARAMS) is True


def test_changed_form_fields_are_rejected():
    signature = _plivo_signs(signed_message(URL, PARAMS, NONCE))
    headers = {SIGNATURE_HEADER: signature, NONCE_HEADER: NONCE}

    assert validate_signature(TOKEN, headers, URL, {**PARAMS, "CallUUID": "another"}) is False


def test_a_signature_over_the_url_and_nonce_alone_is_rejected():
    headers = {SIGNATURE_HEADER: _plivo_signs(URL + NONCE), NONCE_HEADER: NONCE}

    assert validate_signature(TOKEN, headers, URL, PARAMS) is False


def test_one_matching_signature_among_several_is_accepted():
    ours = _plivo_signs(signed_message(URL, PARAMS, NONCE))
    headers = {SIGNATURE_HEADER: f"c29tZW9uZSBlbHNl,{ours}", NONCE_HEADER: NONCE}

    assert validate_signature(TOKEN, headers, URL, PARAMS) is True


# ---- A repeated answer webhook ----

def _services() -> tuple[CallService, TelephonyCallService]:
    call_service = CallService(ConversationService(InMemoryConversationRepository()))
    return call_service, TelephonyCallService(
        call_service, InMemoryTelephonyCallMappingRepository()
    )


def _inbound(call_uuid: str) -> InboundCallEvent:
    return InboundCallEvent(provider_call_id=call_uuid, from_number="+91123", to_number="+91456")


def test_a_repeated_answer_webhook_keeps_the_same_call():
    call_service, telephony = _services()

    first = telephony.start_call_from_provider("plivo", _inbound("uuid-1"))
    second = telephony.start_call_from_provider("plivo", _inbound("uuid-1"))
    other = telephony.start_call_from_provider("plivo", _inbound("uuid-2"))

    assert second == first
    assert other != first
    assert call_service.count_calls() == 2


def test_a_hangup_for_an_unknown_call_is_logged(caplog):
    _, telephony = _services()

    with caplog.at_level(logging.WARNING):
        handled = telephony.handle_status_event(
            CallStatusEvent(provider_call_id="never-answered", status=CallProviderStatus.COMPLETED)
        )

    assert handled is False
    assert "never-answered" in caplog.text


# ---- A hangup that never arrives ----

class _Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def _sweeper(call_service, telephony, clock, completed) -> StaleCallSweeper:
    def complete(call_id: str, end_time: float) -> None:
        completed.append((call_id, end_time))
        call_service.end_call(call_id, end_time)

    return StaleCallSweeper(
        call_service,
        telephony.stream_is_open,
        complete,
        idle_seconds=600.0,
        call_id_prefixes=("plivo-",),
        clock=clock,
    )


def _say(call_service: CallService, call_id: str, index: int) -> None:
    call_service.add_utterance(
        call_id,
        Utterance(
            utterance_id=f"u{index}",
            transcript="The brakes make a noise.",
            speaker_role=SpeakerRole.CUSTOMER,
            languages=("en",),
            start_time=float(index),
            end_time=float(index) + 1.0,
        ),
    )


def test_a_call_with_no_hangup_is_completed_after_ten_quiet_minutes():
    call_service, telephony = _services()
    clock, completed = _Clock(), []
    call_service.start_call("plivo-1", clock.now)
    sweeper = _sweeper(call_service, telephony, clock, completed)

    assert sweeper.run() == 0  # first seen quiet
    clock.now += 599
    assert sweeper.run() == 0
    clock.now += 2
    assert sweeper.run() == 1

    # It ended when it went quiet, not when the sweep got to it.
    assert completed == [("plivo-1", 1_000_000.0)]
    assert call_service.get_call("plivo-1").status is ConversationStatus.COMPLETED
    assert sweeper.run() == 0


def test_a_call_whose_stream_is_open_is_left_alone():
    call_service, telephony = _services()
    clock, completed = _Clock(), []
    call_service.start_call("plivo-1", clock.now)
    telephony.stream_opened("plivo-1")
    sweeper = _sweeper(call_service, telephony, clock, completed)

    sweeper.run()
    clock.now += 3600
    assert sweeper.run() == 0

    # Once the stream has closed, the ten minutes start.
    telephony.stream_drained("plivo-1")
    assert sweeper.run() == 0
    clock.now += 601
    assert sweeper.run() == 1


def test_new_speech_restarts_the_wait():
    call_service, telephony = _services()
    clock, completed = _Clock(), []
    call_service.start_call("plivo-1", clock.now)
    sweeper = _sweeper(call_service, telephony, clock, completed)

    sweeper.run()
    clock.now += 500
    _say(call_service, "plivo-1", 0)
    assert sweeper.run() == 0
    clock.now += 500
    assert sweeper.run() == 0
    clock.now += 101
    assert sweeper.run() == 1


def test_manual_calls_are_never_swept():
    call_service, telephony = _services()
    clock, completed = _Clock(), []
    call_service.start_call("manual-call", clock.now)
    sweeper = _sweeper(call_service, telephony, clock, completed)

    sweeper.run()
    clock.now += 86400
    assert sweeper.run() == 0
    assert call_service.get_call("manual-call").status is ConversationStatus.ACTIVE


def test_one_failing_call_does_not_stop_the_sweep():
    call_service, telephony = _services()
    clock = _Clock()
    call_service.start_call("plivo-1", clock.now)
    call_service.start_call("plivo-2", clock.now)
    completed: list[str] = []

    def complete(call_id: str, end_time: float) -> None:
        if call_id == "plivo-1":
            raise RuntimeError("database is away")
        completed.append(call_id)
        call_service.end_call(call_id, end_time)

    sweeper = StaleCallSweeper(
        call_service,
        telephony.stream_is_open,
        complete,
        idle_seconds=600.0,
        call_id_prefixes=("plivo-",),
        clock=clock,
    )

    sweeper.run()
    clock.now += 601
    assert sweeper.run() == 1
    assert completed == ["plivo-2"]
    # The failed one is tried again at the next sweep.
    assert sweeper.run() == 0
    assert call_service.get_call("plivo-1").status is ConversationStatus.ACTIVE
