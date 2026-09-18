from dataclasses import dataclass
from enum import Enum

from app.core.constants import COMPLAINT_CATEGORIES


class ComplaintCoverageStatus(str, Enum):
    NOT_RAISED = "not_raised"
    DETECTED = "detected"
    PROBED = "probed"
    COVERED = "covered"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


@dataclass
class ComplaintCoverage:
    category: str
    status: ComplaintCoverageStatus = ComplaintCoverageStatus.NOT_RAISED

    def __post_init__(self) -> None:
        if self.category not in COMPLAINT_CATEGORIES:
            raise ValueError(
                f"Unsupported complaint category: {self.category!r}."
            )

    def detect(self) -> None:
        self._move_to(ComplaintCoverageStatus.DETECTED)

    def probe(self) -> None:
        self._move_to(ComplaintCoverageStatus.PROBED)

    def cover(self) -> None:
        self._move_to(ComplaintCoverageStatus.COVERED)

    def resolve(self) -> None:
        self._move_to(ComplaintCoverageStatus.RESOLVED)

    def mark_unresolved(self) -> None:
        self._move_to(ComplaintCoverageStatus.UNRESOLVED)

    def _move_to(self, new_status: ComplaintCoverageStatus) -> None:
        allowed_transitions = {
            ComplaintCoverageStatus.NOT_RAISED: {
                ComplaintCoverageStatus.DETECTED,
            },
            ComplaintCoverageStatus.DETECTED: {
                ComplaintCoverageStatus.PROBED,
            },
            ComplaintCoverageStatus.PROBED: {
                ComplaintCoverageStatus.COVERED,
            },
            ComplaintCoverageStatus.COVERED: {
                ComplaintCoverageStatus.RESOLVED,
                ComplaintCoverageStatus.UNRESOLVED,
            },
            ComplaintCoverageStatus.RESOLVED: set(),
            ComplaintCoverageStatus.UNRESOLVED: set(),
        }

        if new_status not in allowed_transitions[self.status]:
            raise ValueError(
                f"Invalid complaint coverage transition: "
                f"{self.status.value} -> {new_status.value}"
            )

        self.status = new_status