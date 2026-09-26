from collections.abc import Sequence

from app.ai.speaker.provider import (
    DiarizedSegment,
    RoleIdentificationProvider,
    SpeakerRole as AISpeakerRole,
    SpeakerRoleAssignment,
)
from app.domain.speaker_session import SpeakerSession
from app.domain.utterance import SpeakerRole

_AI_TO_DOMAIN: dict[AISpeakerRole, SpeakerRole] = {
    AISpeakerRole.ICR: SpeakerRole.ICR,
    AISpeakerRole.CUSTOMER: SpeakerRole.CUSTOMER,
    AISpeakerRole.UNKNOWN: SpeakerRole.UNKNOWN,
}
_DOMAIN_TO_AI: dict[SpeakerRole, AISpeakerRole] = {
    domain: ai for ai, domain in _AI_TO_DOMAIN.items()
}


class SessionRoleIdentificationProvider(RoleIdentificationProvider):
    def __init__(
        self,
        session: SpeakerSession,
        role_order: Sequence[AISpeakerRole] | None = None,
    ) -> None:
        self._session = session
        self._role_order = tuple(role_order or ())

    def identify_roles(
        self, segments: list[DiarizedSegment]
    ) -> list[SpeakerRoleAssignment]:
        first_start: dict[str, float] = {}
        for segment in segments:
            current = first_start.get(segment.speaker_id)
            if current is None or segment.start_time < current:
                first_start[segment.speaker_id] = segment.start_time

        assignments: list[SpeakerRoleAssignment] = []
        for speaker_id in sorted(first_start, key=first_start.__getitem__):
            mapped_role = self._session.role_for(speaker_id) # SpeakerRole | None
            assignments.append(
                SpeakerRoleAssignment(
                    speaker_id=speaker_id,
                    role=(
                        _DOMAIN_TO_AI[mapped_role]
                        if mapped_role is not None
                        else AISpeakerRole.UNKNOWN
                    ),
                )
            )
        return assignments