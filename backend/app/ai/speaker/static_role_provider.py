from collections.abc import Mapping

from app.ai.speaker.provider import (
    DiarizedSegment,
    RoleIdentificationProvider,
    SpeakerRole,
    SpeakerRoleAssignment,
)


class StaticRoleIdentificationProvider(RoleIdentificationProvider):
    def __init__(self, role_by_speaker: Mapping[str, SpeakerRole]) -> None:
        self._role_by_speaker = dict(role_by_speaker)

    def identify_roles(
        self, segments: list[DiarizedSegment]
    ) -> list[SpeakerRoleAssignment]:
        speaker_ids = dict.fromkeys(segment.speaker_id for segment in segments)
        return [
            SpeakerRoleAssignment(
                speaker_id=speaker_id,
                role=self._role_by_speaker.get(speaker_id, SpeakerRole.UNKNOWN),
            )
            for speaker_id in speaker_ids
        ]