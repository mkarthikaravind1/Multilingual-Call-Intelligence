from collections.abc import Sequence

from app.ai.speaker.order_based_role_provider import DEFAULT_ROLE_ORDER
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
}
_DOMAIN_TO_AI: dict[SpeakerRole, AISpeakerRole] = {
    domain: ai for ai, domain in _AI_TO_DOMAIN.items()
}


class SessionRoleIdentificationProvider(RoleIdentificationProvider):
    def __init__(
        self,
        session: SpeakerSession,
        role_order: Sequence[AISpeakerRole] = DEFAULT_ROLE_ORDER,
    ) -> None:
        self._session = session
        self._role_order = tuple(
            _AI_TO_DOMAIN[role] for role in role_order if role in _AI_TO_DOMAIN
        )

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
            role = self._session.role_for(speaker_id)
            if role is None:
                role = self._next_free_role()
                if role is not None:
                    self._session.assign(speaker_id, role)
            assignments.append(
                SpeakerRoleAssignment(
                    speaker_id=speaker_id,
                    role=_DOMAIN_TO_AI[role] if role else AISpeakerRole.UNKNOWN,
                )
            )
        return assignments

    def _next_free_role(self) -> SpeakerRole | None:
        for role in self._role_order:
            if not self._session.speakers_with_role(role):
                return role
        return None