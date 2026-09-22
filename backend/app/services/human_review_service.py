"""Service for approving or rejecting improvement candidates."""

import time
from dataclasses import replace

from app.domain.improvement_candidate import (
    ImprovementCandidate,
    ImprovementReviewStatus,
)


class HumanReviewService:
    """Handles human approval and rejection of improvement candidates.

    This service only changes the review state. It does not apply the
    improvement to any AI model or modify system behaviour.
    """

    def approve(
        self,
        candidate: ImprovementCandidate,
        reviewed_at: float | None = None,
    ) -> ImprovementCandidate:
        """Approve a candidate that is currently pending review."""

        self._ensure_pending(candidate)

        timestamp = time.time() if reviewed_at is None else reviewed_at
        self._validate_review_timestamp(candidate, timestamp)

        return replace(
            candidate,
            status=ImprovementReviewStatus.APPROVED,
            reviewed_at=timestamp,
        )

    def reject(
        self,
        candidate: ImprovementCandidate,
        reviewed_at: float | None = None,
    ) -> ImprovementCandidate:
        """Reject a candidate that is currently pending review."""

        self._ensure_pending(candidate)

        timestamp = time.time() if reviewed_at is None else reviewed_at
        self._validate_review_timestamp(candidate, timestamp)

        return replace(
            candidate,
            status=ImprovementReviewStatus.REJECTED,
            reviewed_at=timestamp,
        )

    @staticmethod
    def _ensure_pending(
        candidate: ImprovementCandidate,
    ) -> None:
        """Ensure only pending candidates can be reviewed."""

        if candidate.status is not ImprovementReviewStatus.PENDING_REVIEW:
            raise ValueError(
                "Only candidates pending review can be approved or rejected."
            )

    @staticmethod
    def _validate_review_timestamp(
        candidate: ImprovementCandidate,
        reviewed_at: float,
    ) -> None:
        """Validate the timestamp before constructing the new candidate."""

        if isinstance(reviewed_at, bool) or not isinstance(
            reviewed_at, (int, float)
        ):
            raise TypeError("reviewed_at must be a number.")

        if reviewed_at < candidate.created_at:
            raise ValueError(
                "reviewed_at cannot be before created_at."
            )
