import pytest

from app.ai.speaker.order_based_role_provider import OrderBasedRoleIdentificationProvider
from app.ai.speaker.provider import (
    DiarizedSegment,
    RoleIdentificationProvider,
    SpeakerRole,
    SpeakerRoleAssignment,
)


def seg(speaker_id: str, start: float, end: float) -> DiarizedSegment:
    return DiarizedSegment(speaker_id=speaker_id, start_time=start, end_time=end)


def test_is_role_identification_provider() -> None:
    assert isinstance(OrderBasedRoleIdentificationProvider(), RoleIdentificationProvider)


def test_first_speaker_is_icr_second_is_customer() -> None:
    result = OrderBasedRoleIdentificationProvider().identify_roles(
        [seg("A", 0.0, 1.0), seg("B", 1.0, 2.0)]
    )
    assert result == [
        SpeakerRoleAssignment("A", SpeakerRole.ICR),
        SpeakerRoleAssignment("B", SpeakerRole.CUSTOMER),
    ]


def test_order_is_by_first_appearance_not_input_order() -> None:
    result = OrderBasedRoleIdentificationProvider().identify_roles(
        [seg("B", 1.0, 2.0), seg("A", 0.0, 1.0)]
    )
    assert [(a.speaker_id, a.role) for a in result] == [
        ("A", SpeakerRole.ICR),
        ("B", SpeakerRole.CUSTOMER),
    ]


def test_one_assignment_per_speaker_when_speakers_repeat() -> None:
    result = OrderBasedRoleIdentificationProvider().identify_roles(
        [seg("A", 0.0, 1.0), seg("B", 1.0, 2.0), seg("A", 2.0, 3.0)]
    )
    assert [a.speaker_id for a in result] == ["A", "B"]


def test_single_speaker_gets_first_role() -> None:
    result = OrderBasedRoleIdentificationProvider().identify_roles([seg("A", 0.0, 1.0)])
    assert result == [SpeakerRoleAssignment("A", SpeakerRole.ICR)]


def test_extra_speakers_are_unknown() -> None:
    result = OrderBasedRoleIdentificationProvider().identify_roles(
        [seg("A", 0.0, 1.0), seg("B", 1.0, 2.0), seg("C", 2.0, 3.0)]
    )
    assert result[2] == SpeakerRoleAssignment("C", SpeakerRole.UNKNOWN)


def test_no_segments_returns_empty_list() -> None:
    assert OrderBasedRoleIdentificationProvider().identify_roles([]) == []


def test_custom_role_order_is_respected() -> None:
    provider = OrderBasedRoleIdentificationProvider(
        role_order=(SpeakerRole.CUSTOMER, SpeakerRole.ICR)
    )
    result = provider.identify_roles([seg("A", 0.0, 1.0), seg("B", 1.0, 2.0)])
    assert [a.role for a in result] == [SpeakerRole.CUSTOMER, SpeakerRole.ICR]


def test_rejects_empty_role_order() -> None:
    with pytest.raises(ValueError, match="role_order"):
        OrderBasedRoleIdentificationProvider(role_order=())


def test_same_input_gives_same_output() -> None:
    provider = OrderBasedRoleIdentificationProvider()
    segments = [seg("A", 0.0, 1.0), seg("B", 1.0, 2.0)]
    assert provider.identify_roles(segments) == provider.identify_roles(segments)