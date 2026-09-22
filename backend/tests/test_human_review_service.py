"""Tests for HumanReviewService."""

import pytest

from app.domain.improvement_candidate import (
    ImprovementCandidate,
    ImprovementReviewStatus,
    ImprovementType,
)
from app.services.human_review_service import HumanReviewService


def _make_candidate(
    status: ImprovementReviewStatus = ImprovementReviewStatus.PENDING_REVIEW,
    reviewed_at: float | None = None,
) -> ImprovementCandidate:
    return ImprovementCandidate(
        candidate_id="candidate-1",
        improvement_type=ImprovementType.COMPLAINT_DETECTION,
        title="Improve complaint detection",
        description="Recurring complaint detection issue",
        evidence=("evidence-1", "evidence-2"),
        occurrence_count=2,
        confidence=0.85,
        status=status,
        created_at=1_700_000_000.0,
        reviewed_at=reviewed_at,
    )


def test_pending_candidate_can_be_approved():
    service = HumanReviewService()

    candidate = _make_candidate()

    approved = service.approve(
        candidate,
        reviewed_at=1_700_000_100.0,
    )

    assert approved.status is ImprovementReviewStatus.APPROVED
    assert approved.reviewed_at == 1_700_000_100.0
    assert approved.candidate_id == candidate.candidate_id
    assert candidate.status is ImprovementReviewStatus.PENDING_REVIEW


def test_pending_candidate_can_be_rejected():
    service = HumanReviewService()

    candidate = _make_candidate()

    rejected = service.reject(
        candidate,
        reviewed_at=1_700_000_100.0,
    )

    assert rejected.status is ImprovementReviewStatus.REJECTED
    assert rejected.reviewed_at == 1_700_000_100.0
    assert rejected.candidate_id == candidate.candidate_id
    assert candidate.status is ImprovementReviewStatus.PENDING_REVIEW


def test_approved_candidate_cannot_be_approved_again():
    service = HumanReviewService()

    candidate = _make_candidate(
        status=ImprovementReviewStatus.APPROVED,
        reviewed_at=1_700_000_100.0,
    )

    with pytest.raises(ValueError):
        service.approve(candidate)


def test_rejected_candidate_cannot_be_rejected_again():
    service = HumanReviewService()

    candidate = _make_candidate(
        status=ImprovementReviewStatus.REJECTED,
        reviewed_at=1_700_000_100.0,
    )

    with pytest.raises(ValueError):
        service.reject(candidate)


def test_approved_candidate_cannot_be_rejected():
    service = HumanReviewService()

    candidate = _make_candidate(
        status=ImprovementReviewStatus.APPROVED,
        reviewed_at=1_700_000_100.0,
    )

    with pytest.raises(ValueError):
        service.reject(candidate)


def test_rejected_candidate_cannot_be_approved():
    service = HumanReviewService()

    candidate = _make_candidate(
        status=ImprovementReviewStatus.REJECTED,
        reviewed_at=1_700_000_100.0,
    )

    with pytest.raises(ValueError):
        service.approve(candidate)


def test_review_timestamp_cannot_be_before_creation():
    service = HumanReviewService()

    candidate = _make_candidate()

    with pytest.raises(ValueError):
        service.approve(
            candidate,
            reviewed_at=1_699_999_999.0,
        )


def test_approval_preserves_candidate_data():
    service = HumanReviewService()

    candidate = _make_candidate()

    approved = service.approve(
        candidate,
        reviewed_at=1_700_000_100.0,
    )

    assert approved.improvement_type == candidate.improvement_type
    assert approved.title == candidate.title
    assert approved.description == candidate.description
    assert approved.evidence == candidate.evidence
    assert approved.occurrence_count == candidate.occurrence_count
    assert approved.confidence == candidate.confidence
    assert approved.created_at == candidate.created_at
