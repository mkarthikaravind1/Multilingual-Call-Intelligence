from app.ai.speaker.provider import (
    DiarizedSegment,
    SpeakerRole as AISpeakerRole,
    SpeakerRoleAssignment,
)
from app.ai.speaker.session_role_provider import SessionRoleIdentificationProvider
from app.domain.speaker_session import SpeakerSession
from app.domain.utterance import SpeakerRole

ORDER = (AISpeakerRole.ICR, AISpeakerRole.CUSTOMER)


def seg(speaker_id: str, start: float = 0.0, end: float = 1.0) -> DiarizedSegment:
    return DiarizedSegment(speaker_id, start, end)


def roles_of(assignments: list[SpeakerRoleAssignment]) -> dict[str, AISpeakerRole]:
    return {a.speaker_id: a.role for a in assignments}


def make_provider(call_id="call-1", initial=None, order=ORDER):
    session = SpeakerSession(call_id, initial)
    return SessionRoleIdentificationProvider(session, order), session


def test_first_chunk_maps_both_roles_by_start_time():
    provider, _ = make_provider()

    result = roles_of(provider.identify_roles([seg("s1", 1.0, 2.0), seg("s0", 0.0, 1.0)]))

    assert result == {"s0": AISpeakerRole.ICR, "s1": AISpeakerRole.CUSTOMER}


def test_returns_speaker_role_assignments():
    provider, _ = make_provider()

    result = provider.identify_roles([seg("s0")])

    assert all(isinstance(a, SpeakerRoleAssignment) for a in result)


def test_mapping_persists_across_chunks_and_same_speaker_keeps_role():
    provider, session = make_provider()

    first = roles_of(provider.identify_roles([seg("s0")]))
    second = roles_of(provider.identify_roles([seg("s1")]))
    third = roles_of(provider.identify_roles([seg("s1", 0.0, 1.0), seg("s0", 1.0, 2.0)]))
    fourth = roles_of(provider.identify_roles([seg("s0")]))

    assert first == {"s0": AISpeakerRole.ICR}
    assert second == {"s1": AISpeakerRole.CUSTOMER}
    assert third == {"s1": AISpeakerRole.CUSTOMER, "s0": AISpeakerRole.ICR}
    assert fourth == {"s0": AISpeakerRole.ICR}
    assert session.role_for("s0") == SpeakerRole.ICR
    assert session.role_for("s1") == SpeakerRole.CUSTOMER


def test_speaker_beyond_available_roles_is_unknown_and_not_stored():
    provider, session = make_provider()
    provider.identify_roles([seg("s0", 0.0, 1.0), seg("s1", 1.0, 2.0)])

    result = roles_of(provider.identify_roles([seg("s2")]))

    assert result == {"s2": AISpeakerRole.UNKNOWN}
    assert session.role_for("s2") is None


def test_explicit_mapping_is_respected_and_new_speaker_takes_free_role():
    provider, session = make_provider(initial={"agent": SpeakerRole.CUSTOMER})

    result = roles_of(provider.identify_roles([seg("caller")]))

    assert result == {"caller": AISpeakerRole.ICR}
    assert session.role_for("agent") == SpeakerRole.CUSTOMER


def test_explicit_mapping_for_known_speaker_is_returned():
    provider, _ = make_provider(
        initial={"agent": SpeakerRole.ICR, "caller": SpeakerRole.CUSTOMER}
    )

    result = roles_of(provider.identify_roles([seg("caller", 0.0, 1.0), seg("agent", 1.0, 2.0)]))

    assert result == {
        "caller": AISpeakerRole.CUSTOMER,
        "agent": AISpeakerRole.ICR,
    }


def test_conflicting_explicit_assignment_after_auto_mapping_is_rejected():
    import pytest

    from app.domain.speaker_session import SpeakerRoleConflictError

    provider, session = make_provider()
    provider.identify_roles([seg("s0")])

    with pytest.raises(SpeakerRoleConflictError):
        session.assign("s0", SpeakerRole.CUSTOMER)

    assert roles_of(provider.identify_roles([seg("s0")])) == {"s0": AISpeakerRole.ICR}


def test_separate_calls_have_independent_mappings():
    call_one, _ = make_provider("call-1")
    call_two, _ = make_provider("call-2")

    call_one.identify_roles([seg("s0")])
    call_one.identify_roles([seg("s1")])
    result = roles_of(call_two.identify_roles([seg("s1")]))

    assert result == {"s1": AISpeakerRole.ICR}


def test_custom_role_order_is_respected():
    provider, _ = make_provider(order=(AISpeakerRole.CUSTOMER, AISpeakerRole.ICR))

    result = roles_of(provider.identify_roles([seg("s0", 0.0, 1.0), seg("s1", 1.0, 2.0)]))

    assert result == {"s0": AISpeakerRole.CUSTOMER, "s1": AISpeakerRole.ICR}