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
        raise RuntimeError(
            "Order-based speaker role inference has been removed. Use the session-scoped SpeakerSession registry or a static speaker-role mapping."
        )

    def identify_roles(
        self, segments: list[DiarizedSegment]
    ) -> list[SpeakerRoleAssignment]:
        raise RuntimeError(
            "Order-based speaker role inference has been removed. Use the session-scoped SpeakerSession registry or a static speaker-role mapping."
        )