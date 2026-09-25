import inspect
from dataclasses import replace
from unittest.mock import create_autospec

import pytest

from app.domain.improvement_candidate import (
    ImprovementCandidate,
    ImprovementReviewStatus,
    ImprovementType,
)
from app.services import learning_human_review_service as module
from app.services.human_review_service import HumanReviewService
from app.services.learning_human_review_service import LearningHumanReviewService

CREATED_AT = 1_700_000_000.0
REVIEWED_AT = 1_700_000_100.0


def make_candidate(
    status: ImprovementReviewStatus = ImprovementReviewStatus.PENDING_REVIEW,
    reviewed_at: float | None = None,
) -> ImprovementCandidate:
    return ImprovementCandidate(
        candidate_id="candidate-1",
        improvement_type=ImprovementType.COMPLAINT_DETECTION,
        title="Improve complaint detection",
        description="Recurring complaint detection issue",
        evidence=("e1", "e2"),
        occurrence_count=2,
        confidence=0.5,
        status=status,
        created_at=CREATED_AT,
        reviewed_at=reviewed_at,
    )


def build() -> LearningHumanReviewService:
    return LearningHumanReviewService(HumanReviewService())


def test_pending_candidate_can_be_approved():
    approved = build().approve(make_candidate(), reviewed_at=REVIEWED_AT)

    assert approved.status is ImprovementReviewStatus.APPROVED
    assert approved.reviewed_at == REVIEWED_AT


def test_pending_candidate_can_be_rejected():
    rejected = build().reject(make_candidate(), reviewed_at=REVIEWED_AT)

    assert rejected.status is ImprovementReviewStatus.REJECTED
    assert rejected.reviewed_at == REVIEWED_AT


def test_review_metadata_defaults_to_current_time_when_not_given():
    approved = build().approve(make_candidate())

    assert approved.reviewed_at is not None
    assert approved.reviewed_at >= CREATED_AT


@pytest.mark.parametrize(
    "status", [ImprovementReviewStatus.APPROVED, ImprovementReviewStatus.REJECTED]
)
@pytest.mark.parametrize("action", ["approve", "reject"])
def test_non_pending_candidates_cannot_be_reviewed_again(status, action):
    reviewed = make_candidate(status=status, reviewed_at=REVIEWED_AT)

    with pytest.raises(ValueError):
        getattr(build(), action)(reviewed)


def test_review_before_creation_is_rejected():
    with pytest.raises(ValueError):
        build().approve(make_candidate(), reviewed_at=CREATED_AT - 1)


def test_non_numeric_review_timestamp_is_rejected():
    with pytest.raises(TypeError):
        build().reject(make_candidate(), reviewed_at="now")  # type: ignore[arg-type]


def test_existing_human_review_service_is_reused():
    review_service = create_autospec(HumanReviewService, instance=True)
    candidate = make_candidate()
    service = LearningHumanReviewService(review_service)

    approved = service.approve(candidate, reviewed_at=REVIEWED_AT)
    rejected = service.reject(candidate, reviewed_at=REVIEWED_AT)

    review_service.approve.assert_called_once_with(candidate, reviewed_at=REVIEWED_AT)
    review_service.reject.assert_called_once_with(candidate, reviewed_at=REVIEWED_AT)
    assert approved is review_service.approve.return_value
    assert rejected is review_service.reject.return_value


def test_review_only_changes_status_and_reviewed_at():
    candidate = make_candidate()

    approved = build().approve(candidate, reviewed_at=REVIEWED_AT)

    assert approved == replace(
        candidate,
        status=ImprovementReviewStatus.APPROVED,
        reviewed_at=REVIEWED_AT,
    )
    assert candidate.status is ImprovementReviewStatus.PENDING_REVIEW
    assert candidate.reviewed_at is None


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_non_candidate_input_is_rejected(action):
    with pytest.raises(TypeError):
        getattr(build(), action)("not a candidate")


def test_review_boundary_has_no_ai_or_application_dependencies():
    source = inspect.getsource(module)

    for forbidden in ("llm", "groq", "provider", "workflow", "prompt", "apply"):
        assert forbidden not in source.lower()