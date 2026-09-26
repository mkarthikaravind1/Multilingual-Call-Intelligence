from collections.abc import Sequence

from app.ai.speaker.provider import SpeakerRole
from app.ai.speaker.session_role_provider import SessionRoleIdentificationProvider
from app.domain.speaker_session import SpeakerSession
from app.services.speaker_session_registry import SpeakerSessionRegistry


def build_speaker_session_registry() -> SpeakerSessionRegistry:
    return SpeakerSessionRegistry()


def build_session_role_provider(
    session: SpeakerSession,
    role_order: Sequence[SpeakerRole] | None = None,
) -> SessionRoleIdentificationProvider:
    return SessionRoleIdentificationProvider(session, role_order)