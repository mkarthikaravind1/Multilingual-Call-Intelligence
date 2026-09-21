from app.domain.utterance import SpeakerRole
from app.services.speaker_session_registry import SpeakerSessionRegistry


def test_get_or_create_returns_same_session_for_same_call():
    registry = SpeakerSessionRegistry()

    assert registry.get_or_create("call-1") is registry.get_or_create("call-1")


def test_separate_calls_have_independent_mappings():
    registry = SpeakerSessionRegistry()
    registry.get_or_create("call-1").assign("s0", SpeakerRole.ICR)
    registry.get_or_create("call-2").assign("s0", SpeakerRole.CUSTOMER)

    assert registry.get_or_create("call-1").role_for("s0") == SpeakerRole.ICR
    assert registry.get_or_create("call-2").role_for("s0") == SpeakerRole.CUSTOMER


def test_get_returns_none_for_unknown_call():
    assert SpeakerSessionRegistry().get("missing") is None