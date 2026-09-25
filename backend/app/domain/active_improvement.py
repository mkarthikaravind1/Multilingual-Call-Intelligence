import dataclasses
from dataclasses import dataclass
from enum import Enum

from app.domain.improvement_candidate import ImprovementSpecification
from app.domain.learning_evidence import LearningComponent


class ActiveImprovementStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


def _require_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


def _require_timestamp(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number, got {type(value).__name__}.")
    if value < 0:
        raise ValueError(f"{field_name} must not be negative.")


@dataclass(frozen=True)
class ActiveImprovement:
    """An approved improvement registered for future runtime use.

    Purely data: activating one never mutates the ImprovementCandidate it
    came from, and this record has no effect on any AI provider or
    CallWorkflowService by itself (see SL-11 scope)."""

    improvement_id: str
    candidate_id: str
    component: LearningComponent
    specification: ImprovementSpecification
    status: ActiveImprovementStatus
    activated_at: float
    deactivated_at: float | None = None

    def __post_init__(self) -> None:
        _require_id(self.improvement_id, "improvement_id")
        _require_id(self.candidate_id, "candidate_id")

        if not isinstance(self.component, LearningComponent):
            raise TypeError(
                f"component must be a LearningComponent, got {type(self.component).__name__}."
            )
        if not isinstance(self.specification, ImprovementSpecification):
            raise TypeError(
                "specification must be an ImprovementSpecification, "
                f"got {type(self.specification).__name__}."
            )
        if not isinstance(self.status, ActiveImprovementStatus):
            raise TypeError(
                f"status must be an ActiveImprovementStatus, got {type(self.status).__name__}."
            )

        _require_timestamp(self.activated_at, "activated_at")

        if self.deactivated_at is not None:
            _require_timestamp(self.deactivated_at, "deactivated_at")
            if self.deactivated_at < self.activated_at:
                raise ValueError("deactivated_at cannot be before activated_at.")

        if self.status is ActiveImprovementStatus.ACTIVE and self.deactivated_at is not None:
            raise ValueError("ACTIVE improvements must not have deactivated_at set.")
        if self.status is ActiveImprovementStatus.INACTIVE and self.deactivated_at is None:
            raise ValueError("INACTIVE improvements must have deactivated_at set.")

    def deactivate(self, at: float) -> "ActiveImprovement":
        if self.status is ActiveImprovementStatus.INACTIVE:
            return self
        return dataclasses.replace(
            self, status=ActiveImprovementStatus.INACTIVE, deactivated_at=at
        )