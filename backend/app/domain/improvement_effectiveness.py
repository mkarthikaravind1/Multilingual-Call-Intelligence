from dataclasses import dataclass
from enum import Enum


class ImprovementEffectivenessStatus(str, Enum):
    NOT_ENOUGH_EVIDENCE = "not_enough_evidence"
    EVIDENCE_AVAILABLE = "evidence_available"


@dataclass(frozen=True)
class ImprovementEffectivenessResult:
    improvement_id: str
    usage_count: int
    evidence_count: int
    status: ImprovementEffectivenessStatus
    observed_outcomes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.improvement_id.strip():
            raise ValueError("improvement_id must not be empty.")

        if self.usage_count < 0:
            raise ValueError("usage_count must not be negative.")

        if self.evidence_count < 0:
            raise ValueError("evidence_count must not be negative.")

        if not isinstance(
            self.status,
            ImprovementEffectivenessStatus,
        ):
            raise TypeError(
                "status must be a valid ImprovementEffectivenessStatus."
            )

        if not isinstance(self.observed_outcomes, tuple):
            raise TypeError("observed_outcomes must be a tuple.")