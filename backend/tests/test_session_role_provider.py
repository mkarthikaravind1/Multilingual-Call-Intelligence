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


def test_returns_speaker_role_assignments():
    provider, _ = make_provider()

    result = provider.identify_roles([seg("s0")])

    assert all(isinstance(a, SpeakerRoleAssignment) for a in result)


def test_speaker_beyond_available_roles_is_unknown_and_not_stored():
    provider, session = make_provider()
    provider.identify_roles([seg("s0", 0.0, 1.0), seg("s1", 1.0, 2.0)])

    result = roles_of(provider.identify_roles([seg("s2")]))

    assert result == {"s2": AISpeakerRole.UNKNOWN}
    assert session.role_for("s2") is None


def test_explicit_mapping_for_known_speaker_is_returned():
    provider, _ = make_provider(
        initial={"agent": SpeakerRole.ICR, "caller": SpeakerRole.CUSTOMER}
    )

    result = roles_of(provider.identify_roles([seg("caller", 0.0, 1.0), seg("agent", 1.0, 2.0)]))

    assert result == {
        "caller": AISpeakerRole.CUSTOMER,
        "agent": AISpeakerRole.ICR,
    }
