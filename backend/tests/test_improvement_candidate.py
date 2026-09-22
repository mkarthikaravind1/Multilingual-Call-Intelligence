from typing import Any

import pytest

from app.domain.improvement_candidate import (
    ImprovementCandidate,
    ImprovementReviewStatus,
    ImprovementType,
)


def make_candidate(**overrides):
    defaults:dict[str,Any] = dict(
        candidate_id="cand-1",
        improvement_type=ImprovementType.QUESTION_STRATEGY,
        title="Ask about parts availability earlier",
        description="ICRs who ask about parts availability by turn 3 resolve faster.",
        evidence=("call-1: customer asked about parts at turn 8",),
        occurrence_count=5,
        confidence=0.8,
        status=ImprovementReviewStatus.PENDING_REVIEW,
        created_at=0.0,
        reviewed_at=None,
    )
    defaults.update(overrides)
    return ImprovementCandidate(**defaults)


def test_valid_pending_candidate_is_created():
    candidate = make_candidate()
    assert candidate.status is ImprovementReviewStatus.PENDING_REVIEW
    assert candidate.reviewed_at is None


def test_approved_candidate_requires_reviewed_at():
    candidate = make_candidate(status=ImprovementReviewStatus.APPROVED, reviewed_at=10.0)
    assert candidate.status is ImprovementReviewStatus.APPROVED
    assert candidate.reviewed_at == 10.0


def test_rejected_candidate_requires_reviewed_at():
    candidate = make_candidate(status=ImprovementReviewStatus.REJECTED, reviewed_at=10.0)
    assert candidate.status is ImprovementReviewStatus.REJECTED
    assert candidate.reviewed_at == 10.0


def test_approved_without_reviewed_at_is_rejected():
    with pytest.raises(ValueError):
        make_candidate(status=ImprovementReviewStatus.APPROVED, reviewed_at=None)


def test_rejected_without_reviewed_at_is_rejected():
    with pytest.raises(ValueError):
        make_candidate(status=ImprovementReviewStatus.REJECTED, reviewed_at=None)


def test_pending_with_reviewed_at_is_rejected():
    with pytest.raises(ValueError):
        make_candidate(status=ImprovementReviewStatus.PENDING_REVIEW, reviewed_at=10.0)


def test_reviewed_at_before_created_at_is_rejected():
    with pytest.raises(ValueError):
        make_candidate(
            status=ImprovementReviewStatus.APPROVED,
            created_at=10.0,
            reviewed_at=5.0,
        )


def test_empty_candidate_id_is_rejected():
    with pytest.raises(ValueError):
        make_candidate(candidate_id="")


def test_empty_title_is_rejected():
    with pytest.raises(ValueError):
        make_candidate(title="   ")


def test_empty_description_is_rejected():
    with pytest.raises(ValueError):
        make_candidate(description="")


def test_non_enum_improvement_type_is_rejected():
    with pytest.raises(TypeError):
        make_candidate(improvement_type="question_strategy")


def test_non_enum_status_is_rejected():
    with pytest.raises(TypeError):
        make_candidate(status="pending_review")


def test_evidence_must_be_a_tuple():
    with pytest.raises(TypeError):
        make_candidate(evidence=["call-1: something happened"])


def test_empty_evidence_tuple_is_rejected():
    with pytest.raises(ValueError):
        make_candidate(evidence=())


def test_blank_evidence_entry_is_rejected():
    with pytest.raises(ValueError):
        make_candidate(evidence=("   ",))


def test_occurrence_count_must_be_int():
    with pytest.raises(TypeError):
        make_candidate(occurrence_count=2.5)


def test_occurrence_count_rejects_bool():
    with pytest.raises(TypeError):
        make_candidate(occurrence_count=True)


def test_occurrence_count_below_one_is_rejected():
    with pytest.raises(ValueError):
        make_candidate(occurrence_count=0)


def test_confidence_below_zero_is_rejected():
    with pytest.raises(ValueError):
        make_candidate(confidence=-0.1)


def test_confidence_above_one_is_rejected():
    with pytest.raises(ValueError):
        make_candidate(confidence=1.1)


def test_confidence_rejects_bool():
    with pytest.raises(TypeError):
        make_candidate(confidence=True)


def test_negative_created_at_is_rejected():
    with pytest.raises(ValueError):
        make_candidate(created_at=-1.0)


def test_non_numeric_created_at_is_rejected():
    with pytest.raises(TypeError):
        make_candidate(created_at="0.0")


def test_candidate_is_immutable():
    candidate = make_candidate()
    with pytest.raises(AttributeError):
        candidate.title = "changed"  # type: ignore