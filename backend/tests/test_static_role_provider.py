from app.ai.speaker.provider import (
    DiarizedSegment,
    RoleIdentificationProvider,
    SpeakerRole,
    SpeakerRoleAssignment,
)
from app.ai.speaker.static_role_provider import StaticRoleIdentificationProvider

ROLES = {"S1": SpeakerRole.ICR, "S2": SpeakerRole.CUSTOMER}


def seg(speaker_id: str, start: float = 0.0, end: float = 1.0) -> DiarizedSegment:
    return DiarizedSegment(speaker_id=speaker_id, start_time=start, end_time=end)


def test_is_role_identification_provider() -> None:
    assert isinstance(StaticRoleIdentificationProvider(ROLES), RoleIdentificationProvider)


def test_assigns_mapped_roles() -> None:
    result = StaticRoleIdentificationProvider(ROLES).identify_roles(
        [seg("S1"), seg("S2", 1.0, 2.0)]
    )
    assert result == [
        SpeakerRoleAssignment("S1", SpeakerRole.ICR),
        SpeakerRoleAssignment("S2", SpeakerRole.CUSTOMER),
    ]


def test_unmapped_speaker_is_unknown() -> None:
    result = StaticRoleIdentificationProvider(ROLES).identify_roles([seg("S9")])
    assert result == [SpeakerRoleAssignment("S9", SpeakerRole.UNKNOWN)]


def test_role_does_not_depend_on_other_speakers_present() -> None:
    provider = StaticRoleIdentificationProvider(ROLES)
    alone = provider.identify_roles([seg("S2")])
    with_others = provider.identify_roles([seg("S1"), seg("S2", 1.0, 2.0)])
    assert alone[0].role == with_others[1].role == SpeakerRole.CUSTOMER


def test_one_assignment_per_speaker() -> None:
    result = StaticRoleIdentificationProvider(ROLES).identify_roles(
        [seg("S1"), seg("S2", 1.0, 2.0), seg("S1", 2.0, 3.0)]
    )
    assert [a.speaker_id for a in result] == ["S1", "S2"]


def test_no_segments_returns_empty_list() -> None:
    assert StaticRoleIdentificationProvider(ROLES).identify_roles([]) == []


def test_mutating_source_mapping_does_not_affect_provider() -> None:
    roles = dict(ROLES)
    provider = StaticRoleIdentificationProvider(roles)
    roles["S1"] = SpeakerRole.CUSTOMER
    assert provider.identify_roles([seg("S1")])[0].role == SpeakerRole.ICR