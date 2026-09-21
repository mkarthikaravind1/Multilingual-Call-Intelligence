from app.domain.speaker_session import SpeakerSession


class SpeakerSessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, SpeakerSession] = {}

    def get_or_create(self, call_id: str) -> SpeakerSession:
        session = self._sessions.get(call_id)
        if session is None:
            session = SpeakerSession(call_id)
            self._sessions[call_id] = session
        return session

    def get(self, call_id: str) -> SpeakerSession | None:
        return self._sessions.get(call_id)