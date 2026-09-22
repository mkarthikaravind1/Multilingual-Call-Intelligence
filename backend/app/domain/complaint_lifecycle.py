import dataclasses
from dataclasses import dataclass
from enum import Enum

from app.core.constants import COMPLAINT_CATEGORIES


class ComplaintLifecycleStatus(str, Enum):
    """Lifecycle of a single complaint instance across a call and beyond.
    Distinct from ComplaintCoverageStatus (per-category coverage within one
    call): this tracks one raised complaint end-to-end, including the
    pre-detection RAISED state and a post-resolution FOLLOW_UP state that
    ComplaintCoverageStatus has no equivalent for. Shared state names reuse
    ComplaintCoverageStatus's wording (detected/probed/covered/resolved/
    unresolved) for consistency.
    """

    RAISED = "raised"
    DETECTED = "detected"
    PROBED = "probed"
    COVERED = "covered"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    FOLLOW_UP = "follow_up"


_ALLOWED_TRANSITIONS: dict[ComplaintLifecycleStatus, frozenset[ComplaintLifecycleStatus]] = {
    ComplaintLifecycleStatus.RAISED: frozenset({ComplaintLifecycleStatus.DETECTED}),
    ComplaintLifecycleStatus.DETECTED: frozenset({ComplaintLifecycleStatus.PROBED}),
    ComplaintLifecycleStatus.PROBED: frozenset({ComplaintLifecycleStatus.COVERED}),
    ComplaintLifecycleStatus.COVERED: frozenset(
        {ComplaintLifecycleStatus.RESOLVED, ComplaintLifecycleStatus.UNRESOLVED}
    ),
    ComplaintLifecycleStatus.RESOLVED: frozenset({ComplaintLifecycleStatus.FOLLOW_UP}),
    ComplaintLifecycleStatus.UNRESOLVED: frozenset({ComplaintLifecycleStatus.FOLLOW_UP}),
    ComplaintLifecycleStatus.FOLLOW_UP: frozenset(),
}


def _require_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


def _require_timestamp(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number, got {type(value).__name__}.")
    if value < 0:
        raise ValueError(f"{field_name} must not be negative.")


def _require_bool(value: bool, field_name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a bool, got {type(value).__name__}.")


@dataclass(frozen=True)
class ComplaintLifecycleRecord:
    complaint_id: str
    call_id: str
    category: str
    status: ComplaintLifecycleStatus
    first_detected_at: float
    last_updated_at: float
    follow_up_required: bool = False

    def __post_init__(self) -> None:
        _require_id(self.complaint_id, "complaint_id")
        _require_id(self.call_id, "call_id")

        if self.category not in COMPLAINT_CATEGORIES:
            raise ValueError(f"Unsupported complaint category: {self.category!r}.")

        if not isinstance(self.status, ComplaintLifecycleStatus):
            raise TypeError(
                f"status must be a ComplaintLifecycleStatus, got {type(self.status).__name__}."
            )

        _require_timestamp(self.first_detected_at, "first_detected_at")
        _require_timestamp(self.last_updated_at, "last_updated_at")
        if self.last_updated_at < self.first_detected_at:
            raise ValueError("last_updated_at cannot be before first_detected_at.")

        _require_bool(self.follow_up_required, "follow_up_required")

    def transition_to(
        self, new_status: ComplaintLifecycleStatus, at: float, follow_up_required: bool | None = None
    ) -> "ComplaintLifecycleRecord":
        if not isinstance(new_status, ComplaintLifecycleStatus):
            raise TypeError(
                f"new_status must be a ComplaintLifecycleStatus, got {type(new_status).__name__}."
            )
        if new_status not in _ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(
                f"Invalid complaint lifecycle transition: {self.status.value} -> {new_status.value}"
            )
        if at < self.last_updated_at:
            raise ValueError("Transition timestamp cannot be before last_updated_at.")

        return dataclasses.replace(
            self,
            status=new_status,
            last_updated_at=at,
            follow_up_required=(
                self.follow_up_required if follow_up_required is None else follow_up_required
            ),
        )