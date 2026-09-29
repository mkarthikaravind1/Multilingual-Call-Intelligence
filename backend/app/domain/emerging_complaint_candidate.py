import dataclasses
from dataclasses import dataclass
from enum import Enum

from app.core.constants import COMPLAINT_CATEGORIES


class EmergingComplaintReviewStatus(str, Enum):
    """Human-review state of a candidate: a supervisor accepts it as a real
    complaint theme or rejects it as noise, and can reopen either decision."""

    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class EmergingComplaintReviewError(ValueError):
    pass


def _optional_text(value: str | None, field_name: str) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError(f"{field_name} must not be blank when provided.")


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
    # Calls the theme was seen on, when the provider knows them.
    call_ids: tuple[str, ...] = ()
    # Set when the candidate is stored; 0.0 for a freshly discovered one.
    first_seen_at: float = 0.0
    last_seen_at: float = 0.0
    reviewed_by: str | None = None
    reviewed_at: float | None = None
    review_note: str | None = None

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
        if not isinstance(self.call_ids, tuple) or not all(
            isinstance(call_id, str) and call_id.strip() for call_id in self.call_ids
        ):
            raise ValueError("call_ids must be a tuple of non-empty strings.")
        if self.last_seen_at < self.first_seen_at:
            raise ValueError("last_seen_at cannot be before first_seen_at.")
        _optional_text(self.reviewed_by, "reviewed_by")
        _optional_text(self.review_note, "review_note")

    def first_stored(self, at: float) -> "EmergingComplaintCandidate":
        return dataclasses.replace(self, first_seen_at=at, last_seen_at=at)

    def refreshed_from(
        self, discovered: "EmergingComplaintCandidate", at: float
    ) -> "EmergingComplaintCandidate":
        """Take the latest evidence from a new discovery run while keeping
        this candidate's identity, history and review decision."""
        return dataclasses.replace(
            self,
            proposed_name=discovered.proposed_name,
            description=discovered.description,
            evidence=discovered.evidence,
            occurrence_count=discovered.occurrence_count,
            confidence=discovered.confidence,
            related_category=discovered.related_category or self.related_category,
            call_ids=discovered.call_ids or self.call_ids,
            last_seen_at=max(at, self.last_seen_at),
        )

    def review(
        self,
        decision: EmergingComplaintReviewStatus,
        by: str,
        at: float,
        note: str | None = None,
    ) -> "EmergingComplaintCandidate":
        """Accept, reject, or reopen (back to pending_review) the candidate."""
        if not isinstance(decision, EmergingComplaintReviewStatus):
            raise TypeError("decision must be an EmergingComplaintReviewStatus.")
        if decision is self.status:
            raise EmergingComplaintReviewError(
                f"Candidate {self.candidate_id!r} is already {decision.value}."
            )
        if decision is EmergingComplaintReviewStatus.PENDING_REVIEW:
            return dataclasses.replace(
                self, status=decision, reviewed_by=None, reviewed_at=None, review_note=None
            )
        return dataclasses.replace(
            self,
            status=decision,
            reviewed_by=by,
            reviewed_at=at,
            review_note=note.strip() if note and note.strip() else None,
        )
