"""A call that ends while the speech models are still loading (the first
call right after a restart) waits for them, so its queued audio is
transcribed instead of being thrown away with the call's completion."""

import threading
import time

from app.services.call_service import CallService
from app.services.conversation_service import ConversationService
from app.services.in_memory_conversation_repository import InMemoryConversationRepository
from app.services.live_state_store import InMemoryLiveStateStore
from app.services.model_warm_up import ModelWarmUp
from app.services.telephony_call_mapping_repository import (
    InMemoryTelephonyCallMappingRepository,
)
from app.services.telephony_call_service import TelephonyCallService


def _telephony(is_warming_up=None, timeout=0.2, limit=1.0, store=None) -> TelephonyCallService:
    return TelephonyCallService(
        CallService(ConversationService(InMemoryConversationRepository())),
        InMemoryTelephonyCallMappingRepository(),
        stream_drain_timeout_seconds=timeout,
        live_state=store or InMemoryLiveStateStore(),
        is_warming_up=is_warming_up,
        warm_up_drain_limit_seconds=limit,
    )


def test_loading_is_in_progress_only_between_its_start_and_its_end():
    release = threading.Event()
    warm_up = ModelWarmUp(lambda: release.wait(5))
    assert not warm_up.in_progress  # not started: nothing to wait for

    thread = threading.Thread(target=warm_up.run)
    thread.start()
    time.sleep(0.05)
    assert warm_up.in_progress

    release.set()
    thread.join(5)
    assert not warm_up.in_progress


def test_a_failed_load_is_logged_and_ends_the_waiting(caplog):
    def fail():
        raise RuntimeError("model file missing")

    warm_up = ModelWarmUp(fail)

    warm_up.run()

    assert not warm_up.in_progress
    assert "Speech models could not be preloaded: model file missing" in caplog.text


def test_a_call_ending_during_loading_waits_past_the_usual_timeout():
    warming = threading.Event()
    warming.set()
    telephony = _telephony(warming.is_set, timeout=0.2, limit=5.0)
    telephony.stream_opened("c1")
    # Loading ends after 0.6 s (three times the usual timeout); the queued
    # audio is processed and the stream drains just after.
    threading.Timer(0.6, warming.clear).start()
    threading.Timer(0.7, telephony.stream_drained, args=("c1",)).start()

    started = time.monotonic()
    drained = telephony.wait_for_stream_drain("c1")

    assert drained is True
    assert 0.6 < time.monotonic() - started < 2.0


def test_once_loading_is_over_the_usual_timeout_applies_again():
    warming = threading.Event()
    warming.set()
    telephony = _telephony(warming.is_set, timeout=0.2, limit=5.0)
    telephony.stream_opened("c1")
    threading.Timer(0.4, warming.clear).start()  # and the stream never drains

    started = time.monotonic()
    drained = telephony.wait_for_stream_drain("c1")

    assert drained is False
    assert 0.5 < time.monotonic() - started < 1.5


def test_loading_that_never_ends_does_not_hold_a_call_open_for_ever():
    telephony = _telephony(lambda: True, timeout=0.1, limit=0.5)
    telephony.stream_opened("c1")

    started = time.monotonic()
    drained = telephony.wait_for_stream_drain("c1")

    assert drained is False
    assert 0.4 < time.monotonic() - started < 1.5


def test_without_loading_the_wait_is_as_before():
    telephony = _telephony(timeout=0.2)
    telephony.stream_opened("c1")

    started = time.monotonic()
    assert telephony.wait_for_stream_drain("c1") is False
    assert 0.15 < time.monotonic() - started < 1.0

    telephony.stream_opened("c2")
    threading.Timer(0.05, telephony.stream_drained, args=("c2",)).start()
    assert telephony.wait_for_stream_drain("c2") is True


def test_a_stream_on_another_instance_is_waited_for_during_loading_too():
    store = InMemoryLiveStateStore()
    store.set_json("stream:c1", True)
    warming = threading.Event()
    warming.set()
    telephony = _telephony(warming.is_set, timeout=0.2, limit=5.0, store=store)
    threading.Timer(0.5, warming.clear).start()
    threading.Timer(0.6, store.delete, args=("stream:c1",)).start()

    started = time.monotonic()
    assert telephony.wait_for_stream_drain("c1") is True
    assert time.monotonic() - started > 0.5
