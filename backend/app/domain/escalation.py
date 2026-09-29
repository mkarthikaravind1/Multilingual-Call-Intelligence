"""Escalation: a call at risk of going wrong that needs a supervisor.

The level of a call's escalation only ever rises during the call, so a
call cannot quietly drop out of the supervisors' queue. Supervisors move an
escalation from OPEN to ACKNOWLEDGED to RESOLVED.
"""

import dataclasses
from dataclasses import dataclass
from enum import Enum


class EscalationLevel(str, Enum):
    NONE = "none"
    WATCH = "watch"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _LEVEL_RANK[self]

    @classmethod
    def highest(cls, *levels: "EscalationLevel") -> "EscalationLevel":
        return max(levels, key=lambda level: level.rank, default=cls.NONE)


_LEVEL_RANK = {
    EscalationLevel.NONE: 0,
    EscalationLevel.WATCH: 1,
    EscalationLevel.HIGH: 2,
    EscalationLevel.CRITICAL: 3,
}


class EscalationSignalType(str, Enum):
    MANAGER_REQUEST = "manager_request"
    LEGAL_THREAT = "legal_threat"
    PUBLIC_COMPLAINT = "public_complaint"
    CANCELLATION = "cancellation"
    NEGATIVE_TONE = "negative_tone"
    UNRESOLVED_COMPLAINTS = "unresolved_complaints"
    OTHER = "other"


class EscalationStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


@dataclass(frozen=True)
class EscalationSignal:
    """One reason a call is escalating, in words a supervisor can act on."""

    signal_type: EscalationSignalType
    level: EscalationLevel
    description: str
    evidence: str | None = None  # what the customer said, when relevant

    def __post_init__(self) -> None:
        if not isinstance(self.signal_type, EscalationSignalType):
            raise TypeError("signal_type must be an EscalationSignalType.")
        if not isinstance(self.level, EscalationLevel):
            raise TypeError("level must be an EscalationLevel.")
        if self.level is EscalationLevel.NONE:
            raise ValueError("A signal must raise the level above none.")
        _require_text(self.description, "description")
        if self.evidence is not None:
            _require_text(self.evidence, "evidence")


@dataclass(frozen=True)
class EscalationAssessment:
    """A detector's view of the call right now."""

    level: EscalationLevel
    signals: tuple[EscalationSignal, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.level, EscalationLevel):
            raise TypeError("level must be an EscalationLevel.")
        if self.level is EscalationLevel.NONE and self.signals:
            raise ValueError("A call with signals cannot be at level none.")
        if self.level is not EscalationLevel.NONE and not self.signals:
            raise ValueError("An escalated call needs at least one signal.")


def merge_signals(
    current: tuple[EscalationSignal, ...], new: tuple[EscalationSignal, ...]
) -> tuple[EscalationSignal, ...]:
    """Keep one signal per type: the higher level, else the earliest."""
    by_type: dict[EscalationSignalType, EscalationSignal] = {}
    for signal in (*current, *new):
        kept = by_type.get(signal.signal_type)
        if kept is None or signal.level.rank > kept.level.rank:
            by_type[signal.signal_type] = signal
    return tuple(
        sorted(by_type.values(), key=lambda s: (-s.level.rank, s.signal_type.value))
    )


@dataclass(frozen=True)
class Escalation:
    """The escalation record of one call (keyed by call_id)."""

    call_id: str
    level: EscalationLevel
    signals: tuple[EscalationSignal, ...]
    status: EscalationStatus
    first_detected_at: float
    updated_at: float
    acknowledged_by: str | None = None
    acknowledged_at: float | None = None
    resolved_by: str | None = None
    resolved_at: float | None = None
    resolution_note: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.call_id, "call_id")
        if not isinstance(self.level, EscalationLevel) or self.level is EscalationLevel.NONE:
            raise ValueError("An escalation must have a level above none.")
        if not self.signals:
            raise ValueError("An escalation needs at least one signal.")
        if not isinstance(self.status, EscalationStatus):
            raise TypeError("status must be an EscalationStatus.")
        if (self.acknowledged_by is None) != (self.acknowledged_at is None):
            raise ValueError("acknowledged_by and acknowledged_at go together.")
        if (self.resolved_by is None) != (self.resolved_at is None):
            raise ValueError("resolved_by and resolved_at go together.")
        if self.status is EscalationStatus.RESOLVED and self.resolved_at is None:
            raise ValueError("A resolved escalation needs resolved_by and resolved_at.")
        if self.status is not EscalationStatus.RESOLVED and self.resolved_at is not None:
            raise ValueError("Only a resolved escalation has resolution details.")

    @property
    def is_active(self) -> bool:
        return self.status is not EscalationStatus.RESOLVED

    def raise_with(self, assessment: EscalationAssessment, at: float) -> "Escalation":
        """Fold a new assessment in. The level only rises; a rise above the
        level a supervisor resolved reopens the escalation."""
        level = EscalationLevel.highest(self.level, assessment.level)
        signals = merge_signals(self.signals, assessment.signals)
        if level is self.level and signals == self.signals:
            return self
        changes: dict = {"level": level, "signals": signals, "updated_at": at}
        if self.status is EscalationStatus.RESOLVED and level.rank > self.level.rank:
            changes.update(
                status=EscalationStatus.OPEN,
                resolved_by=None,
                resolved_at=None,
                resolution_note=None,
            )
        return dataclasses.replace(self, **changes)

    def acknowledge(self, by: str, at: float) -> "Escalation":
        if self.status is not EscalationStatus.OPEN:
            raise EscalationTransitionError(
                f"Only an open escalation can be acknowledged; this one is {self.status.value}."
            )
        _require_text(by, "by")
        return dataclasses.replace(
            self,
            status=EscalationStatus.ACKNOWLEDGED,
            acknowledged_by=by,
            acknowledged_at=at,
            updated_at=at,
        )

    def resolve(self, by: str, at: float, note: str | None = None) -> "Escalation":
        if self.status is EscalationStatus.RESOLVED:
            raise EscalationTransitionError("This escalation is already resolved.")
        _require_text(by, "by")
        return dataclasses.replace(
            self,
            status=EscalationStatus.RESOLVED,
            resolved_by=by,
            resolved_at=at,
            resolution_note=note.strip() if note and note.strip() else None,
            updated_at=at,
        )


class EscalationTransitionError(Exception):
    pass
