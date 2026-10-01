import logging
from collections.abc import Callable, Mapping

from app.domain.speaker_session import SpeakerSession
from app.domain.utterance import SpeakerRole
from app.services.live_state_store import LiveStateStore

logger = logging.getLogger(__name__)

# Speaker roles only matter while the call is live.
SPEAKER_ROLES_TTL_SECONDS = 6 * 60 * 60


class _SharedSpeakerSession(SpeakerSession):
    """A SpeakerSession that writes every role change through to the shared
    store, so a stream that reconnects to another instance keeps its roles."""

    def __init__(
        self,
        call_id: str,
        initial_roles: Mapping[str, SpeakerRole],
        on_change: Callable[[SpeakerSession], None],
    ) -> None:
        super().__init__(call_id, initial_roles)
        self._on_change = on_change

    def assign(self, speaker_id: str, role: SpeakerRole) -> None:
        super().assign(speaker_id, role)
        self._on_change(self)

    def assign_many(self, roles: Mapping[str, SpeakerRole]) -> None:
        super().assign_many(roles)
        # Also runs from __init__, before the callback exists.
        if getattr(self, "_on_change", None) is not None:
            self._on_change(self)


class SpeakerSessionRegistry:
    def __init__(self, store: LiveStateStore | None = None) -> None:
        self._sessions: dict[str, SpeakerSession] = {}
        self._store = store

    def get_or_create(self, call_id: str) -> SpeakerSession:
        if self._store is not None:
            return self._shared_session(call_id)
        session = self._sessions.get(call_id)
        if session is None:
            session = SpeakerSession(call_id)
            self._sessions[call_id] = session
        return session

    def get(self, call_id: str) -> SpeakerSession | None:
        if self._store is not None:
            return self._shared_session(call_id) if self._load(call_id) else None
        return self._sessions.get(call_id)

    def _shared_session(self, call_id: str) -> SpeakerSession:
        return _SharedSpeakerSession(call_id, self._load(call_id), self._save)

    def _load(self, call_id: str) -> dict[str, SpeakerRole]:
        try:
            raw = self._store.get_json(_key(call_id)) or {}
            return {speaker: SpeakerRole(role) for speaker, role in raw.items()}
        except Exception:
            logger.exception("Could not read the speaker roles of call %r", call_id)
            return {}

    def _save(self, session: SpeakerSession) -> None:
        try:
            self._store.set_json(
                _key(session.call_id),
                {speaker: role.value for speaker, role in session.roles.items()},
                ttl_seconds=SPEAKER_ROLES_TTL_SECONDS,
            )
        except Exception:
            logger.exception("Could not share the speaker roles of call %r", session.call_id)


def _key(call_id: str) -> str:
    return f"speakers:{call_id}"
