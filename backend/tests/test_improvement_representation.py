"""Tests for SL-10: structured improvement representation."""

from typing import Any

from app.domain.improvement_candidate import (
    ImprovementCandidate,
    ImprovementReviewStatus,
    ImprovementSpecification,
    ImprovementType,
)
from app.domain.learning_evidence import LearningComponent
from app.domain.learning_pattern import LearningPattern
from app.services.human_review_service import HumanReviewService
from app.services.improvement_candidate_service import ImprovementCandidateService

import pytest


def make_pattern(**overrides) -> LearningPattern:
    defaults:dict[str,Any] = dict(
        pattern_id="pattern-1",
        component=LearningComponent.COMPLAINT_DETECTION,
        description="Recurring issue detected in complaint_detection: 'delay' observed 3 times.",
        occurrence_count=3,
        evidence_ids=["evidence-1", "evidence-2", "evidence-3"],
        suggested_improvement="Investigate and address the recurring 'delay' issue.",
        created_at=1_700_000_000.0,
    )
    defaults.update(overrides)
    return LearningPattern(**defaults)


def test_candidate_can_hold_a_specification():
    spec = ImprovementSpecification(
        component=LearningComponent.COMPLAINT_DETECTION,
        current_behavior="observed X",
        proposed_behavior="proposed Y",
        reason="recurred 3 times",
    )
    candidate = ImprovementCandidate(
        candidate_id="c1",
        improvement_type=ImprovementType.COMPLAINT_DETECTION,
        title="t",
        description="d",
        evidence=("e1",),
        occurrence_count=1,
        confidence=0.5,
        status=ImprovementReviewStatus.PENDING_REVIEW,
        created_at=0.0,
        specification=spec,
    )
    assert candidate.specification is spec


def test_candidate_specification_defaults_to_none():
    candidate = ImprovementCandidate(
        candidate_id="c1",
        improvement_type=ImprovementType.COMPLAINT_DETECTION,
        title="t",
        description="d",
        evidence=("e1",),
        occurrence_count=1,
        confidence=0.5,
        status=ImprovementReviewStatus.PENDING_REVIEW,
        created_at=0.0,
    )
    assert candidate.specification is None


def test_invalid_specification_type_is_rejected():
    with pytest.raises(TypeError):
        ImprovementCandidate(
            candidate_id="c1",
            improvement_type=ImprovementType.COMPLAINT_DETECTION,
            title="t",
            description="d",
            evidence=("e1",),
            occurrence_count=1,
            confidence=0.5,
            status=ImprovementReviewStatus.PENDING_REVIEW,
            created_at=0.0,
            specification="not a spec",  # type: ignore
        )


def test_specification_rejects_invalid_component():
    with pytest.raises(TypeError):
        ImprovementSpecification(
            component="complaint_detection",  # type: ignore
            current_behavior="a",
            proposed_behavior="b",
            reason="c",
        )


@pytest.mark.parametrize("field", ["current_behavior", "proposed_behavior", "reason"])
def test_specification_rejects_blank_text_fields(field):
    values:dict[str,Any] = dict(
        component=LearningComponent.COMPLAINT_DETECTION,
        current_behavior="a",
        proposed_behavior="b",
        reason="c",
    )
    values[field] = "   "
    with pytest.raises(ValueError):
        ImprovementSpecification(**values)


def test_candidate_generation_populates_specification_from_pattern():
    pattern = make_pattern()
    candidate = ImprovementCandidateService().create_candidate(
        pattern, confidence=0.8, created_at=100.0
    )

    assert candidate.specification is not None
    assert candidate.specification.component == LearningComponent.COMPLAINT_DETECTION
    assert candidate.specification.current_behavior == pattern.description
    assert candidate.specification.proposed_behavior == pattern.suggested_improvement
    assert "3 time(s)" in candidate.specification.reason


def test_specification_status_starts_pending_review():
    candidate = ImprovementCandidateService().create_candidate(
        make_pattern(), confidence=0.8, created_at=100.0
    )
    assert candidate.status is ImprovementReviewStatus.PENDING_REVIEW


def test_existing_component_mapping_still_works():
    candidate = ImprovementCandidateService().create_candidate(
        make_pattern(component=LearningComponent.NEXT_QUESTION),
        confidence=0.8,
        created_at=100.0,
    )
    assert candidate.improvement_type is ImprovementType.QUESTION_STRATEGY
    assert candidate.specification is not None
    assert candidate.specification.component == LearningComponent.NEXT_QUESTION


def test_approval_preserves_specification():
    candidate = ImprovementCandidateService().create_candidate(
        make_pattern(), confidence=0.8, created_at=100.0
    )
    approved = HumanReviewService().approve(candidate, reviewed_at=200.0)

    assert approved.status is ImprovementReviewStatus.APPROVED
    assert approved.specification == candidate.specification


def test_rejection_preserves_specification():
    candidate = ImprovementCandidateService().create_candidate(
        make_pattern(), confidence=0.8, created_at=100.0
    )
    rejected = HumanReviewService().reject(candidate, reviewed_at=200.0)

    assert rejected.status is ImprovementReviewStatus.REJECTED
    assert rejected.specification == candidate.specification


def test_no_runtime_ai_behavior_is_touched():
    """SL-10 is representation-only: creating a candidate must not require
    or trigger any AI/provider call — the service takes plain data in."""
    candidate = ImprovementCandidateService().create_candidate(
        make_pattern(), confidence=0.8, created_at=100.0
    )
    assert isinstance(candidate.specification, ImprovementSpecification)