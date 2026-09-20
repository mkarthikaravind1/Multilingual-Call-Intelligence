from collections.abc import Sequence

from app.ai.speaker.provider import (
    DiarizedSegment,
    RoleIdentificationProvider,
    SpeakerRole,
    SpeakerRoleAssignment,
)

DEFAULT_ROLE_ORDER: tuple[SpeakerRole, ...] = (SpeakerRole.ICR, SpeakerRole.CUSTOMER)


class OrderBasedRoleIdentificationProvider(RoleIdentificationProvider):
    def __init__(self, role_order: Sequence[SpeakerRole] = DEFAULT_ROLE_ORDER) -> None:
        if not role_order:
            raise ValueError("role_order must not be empty.")
        self._role_order = tuple(role_order)

    def identify_roles(
        self, segments: list[DiarizedSegment]
    ) -> list[SpeakerRoleAssignment]:
        speaker_ids = list(
            dict.fromkeys(
                segment.speaker_id
                for segment in sorted(segments, key=lambda s: s.start_time)
            )
        )
        return [
            SpeakerRoleAssignment(
                speaker_id=speaker_id,
                role=(
                    self._role_order[index]
                    if index < len(self._role_order)
                    else SpeakerRole.UNKNOWN
                ),
            )
            for index, speaker_id in enumerate(speaker_ids)
        ]