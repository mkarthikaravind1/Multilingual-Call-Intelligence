import pytest

from app.domain.speaker_session import SpeakerRoleConflictError, SpeakerSession
from app.domain.utterance import SpeakerRole


def test_unknown_speaker_has_no_role():
    assert SpeakerSession("call-1").role_for("s0") is None


def test_assigned_role_persists_and_supports_both_roles():
    session = SpeakerSession("call-1")

    session.assign("s0", SpeakerRole.ICR)
    session.assign("s1", SpeakerRole.CUSTOMER)

    assert session.role_for("s0") == SpeakerRole.ICR
    assert session.role_for("s1") == SpeakerRole.CUSTOMER
    assert session.speakers_with_role(SpeakerRole.ICR) == ("s0",)
    assert session.speakers_with_role(SpeakerRole.CUSTOMER) == ("s1",)


def test_reassigning_same_role_is_allowed():
    session = SpeakerSession("call-1")
    session.assign("s0", SpeakerRole.ICR)

    session.assign("s0", SpeakerRole.ICR)

    assert session.role_for("s0") == SpeakerRole.ICR


def test_conflicting_assignment_is_rejected_and_mapping_is_unchanged():
    session = SpeakerSession("call-1")
    session.assign("s0", SpeakerRole.ICR)

    with pytest.raises(SpeakerRoleConflictError, match="already mapped"):
        session.assign("s0", SpeakerRole.CUSTOMER)

    assert session.role_for("s0") == SpeakerRole.ICR


def test_initial_roles_are_applied():
    session = SpeakerSession(
        "call-1", {"agent": SpeakerRole.ICR, "caller": SpeakerRole.CUSTOMER}
    )

    assert session.role_for("agent") == SpeakerRole.ICR
    assert session.role_for("caller") == SpeakerRole.CUSTOMER


def test_assign_many_is_atomic_on_conflict():
    session = SpeakerSession("call-1", {"s0": SpeakerRole.ICR})

    with pytest.raises(SpeakerRoleConflictError):
        session.assign_many({"s1": SpeakerRole.CUSTOMER, "s0": SpeakerRole.CUSTOMER})

    assert session.role_for("s1") is None
    assert session.role_for("s0") == SpeakerRole.ICR


def test_roles_view_is_read_only_snapshot():
    session = SpeakerSession("call-1", {"s0": SpeakerRole.ICR})
    snapshot = session.roles

    with pytest.raises(TypeError):
        snapshot["s1"] = SpeakerRole.CUSTOMER  # type: ignore[index]

    session.assign("s1", SpeakerRole.CUSTOMER)
    assert "s1" not in snapshot


def test_empty_call_id_is_rejected():
    with pytest.raises(ValueError, match="call_id"):
        SpeakerSession("  ")


@pytest.mark.parametrize("speaker_id", ["", "   "])
def test_empty_speaker_id_is_rejected(speaker_id):
    with pytest.raises(ValueError, match="speaker_id"):
        SpeakerSession("call-1").assign(speaker_id, SpeakerRole.ICR)


def test_non_role_value_is_rejected():
    with pytest.raises(ValueError, match="role"):
        SpeakerSession("call-1").assign("s0", "ICR")  # type: ignore[arg-type]