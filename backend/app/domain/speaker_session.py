from collections.abc import Mapping
from types import MappingProxyType

from app.domain.utterance import SpeakerRole


class SpeakerRoleConflictError(ValueError):
    pass


class SpeakerSession:
    def __init__(
        self, call_id: str, initial_roles: Mapping[str, SpeakerRole] | None = None
    ) -> None:
        if not call_id.strip():
            raise ValueError("call_id must not be empty.")
        self._call_id = call_id
        self._roles: dict[str, SpeakerRole] = {}
        if initial_roles:
            self.assign_many(initial_roles)

    @property
    def call_id(self) -> str:
        return self._call_id

    @property
    def roles(self) -> Mapping[str, SpeakerRole]:
        return MappingProxyType(dict(self._roles))

    def role_for(self, speaker_id: str) -> SpeakerRole | None:
        return self._roles.get(speaker_id)

    def speakers_with_role(self, role: SpeakerRole) -> tuple[str, ...]:
        return tuple(s for s, r in self._roles.items() if r == role)

    def assign(self, speaker_id: str, role: SpeakerRole) -> None:
        self._check(speaker_id, role)
        self._roles[speaker_id] = role

    def assign_many(self, roles: Mapping[str, SpeakerRole]) -> None:
        for speaker_id, role in roles.items():
            self._check(speaker_id, role)
        self._roles.update(roles)

    def _check(self, speaker_id: str, role: SpeakerRole) -> None:
        if not isinstance(speaker_id, str) or not speaker_id.strip():
            raise ValueError("speaker_id must not be empty.")
        if not isinstance(role, SpeakerRole):
            raise ValueError("role must be a SpeakerRole.")
        existing = self._roles.get(speaker_id)
        if existing is not None and existing != role:
            raise SpeakerRoleConflictError(
                f"Speaker {speaker_id!r} in call {self._call_id!r} is already "
                f"mapped to {existing.value}; cannot remap to {role.value}."
            )