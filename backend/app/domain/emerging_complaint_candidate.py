from dataclasses import dataclass
from enum import Enum

from app.core.constants import COMPLAINT_CATEGORIES


class EmergingComplaintReviewStatus(str, Enum):
    """Human-review state of a candidate. Transitions are not modelled yet —
    this milestone is data-only; a future milestone will add the workflow
    that moves candidates between these states.
    """

    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


def _require_confidence(value: float) -> None:
    # bool is a subclass of int, so it must be rejected explicitly.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"confidence must be a number, got {type(value).__name__}.")
    # Written as a positive range check so NaN is rejected too.
    if not (0.0 <= value <= 1.0):
        raise ValueError("confidence must be between 0.0 and 1.0.")


def _require_evidence(value: tuple) -> None:
    if not isinstance(value, tuple) or not value:
        raise ValueError("evidence must be a non-empty tuple of strings.")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError("evidence must be a non-empty tuple of non-empty strings.")


@dataclass(frozen=True)
class EmergingComplaintCandidate:
    """A potential new complaint category surfaced from conversations, pending
    human review. Distinct from ComplaintCoverage/ComplaintSummary, which track
    an already-recognized category (from COMPLAINT_CATEGORIES) within a single
    call; this represents a pattern that recurs across calls and does not yet
    correspond to a known category.

    This is a pure data model: no discovery, clustering, persistence, or
    review-transition logic lives here.
    """

    candidate_id: str
    proposed_name: str
    description: str
    evidence: tuple[str, ...]
    occurrence_count: int
    confidence: float
    related_category: str | None = None
    status: EmergingComplaintReviewStatus = EmergingComplaintReviewStatus.PENDING_REVIEW

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must not be empty.")

        if not self.proposed_name.strip():
            raise ValueError("proposed_name must not be empty.")
        if self.proposed_name in COMPLAINT_CATEGORIES:
            raise ValueError(
                f"proposed_name {self.proposed_name!r} already exists in "
                "COMPLAINT_CATEGORIES; an emerging candidate must propose a new category."
            )

        if not self.description.strip():
            raise ValueError("description must not be empty.")

        _require_evidence(self.evidence)

        if (
            isinstance(self.occurrence_count, bool)
            or not isinstance(self.occurrence_count, int)
            or self.occurrence_count < 1
        ):
            raise ValueError("occurrence_count must be a positive integer.")

        _require_confidence(self.confidence)

        if self.related_category is not None:
            if not isinstance(self.related_category, str):
                raise TypeError(
                    "related_category must be a string or None, "
                    f"got {type(self.related_category).__name__}."
                )
            if self.related_category not in COMPLAINT_CATEGORIES:
                raise ValueError(
                    f"Unsupported related_category: {self.related_category!r}. "
                    f"Must be one of {COMPLAINT_CATEGORIES} or None."
                )

        if not isinstance(self.status, EmergingComplaintReviewStatus):
            raise TypeError(
                "status must be an EmergingComplaintReviewStatus, "
                f"got {type(self.status).__name__}."
            )