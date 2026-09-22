"""Tests for ImprovementCandidateService."""

from app.domain.improvement_candidate import (
    ImprovementReviewStatus,
    ImprovementType,
)
from app.domain.learning_evidence import LearningComponent
from app.domain.learning_pattern import LearningPattern
from app.services.improvement_candidate_service import (
    ImprovementCandidateService,
)


def _make_pattern(
    component: LearningComponent = LearningComponent.COMPLAINT_DETECTION,
) -> LearningPattern:
    return LearningPattern(
        pattern_id="pattern-1",
        component=component,
        description="Recurring complaint detection issue",
        occurrence_count=3,
        evidence_ids=["evidence-1", "evidence-2", "evidence-3"],
        suggested_improvement="Improve complaint detection logic.",
        created_at=1_700_000_000.0,
    )


def test_pattern_creates_pending_candidate():
    service = ImprovementCandidateService()

    candidate = service.create_candidate(
        _make_pattern(),
        confidence=0.85,
        created_at=1_700_000_100.0,
    )

    assert candidate.candidate_id.startswith("candidate-")
    assert candidate.improvement_type is ImprovementType.COMPLAINT_DETECTION
    assert candidate.title == "Improve complaint detection"
    assert candidate.description == "Recurring complaint detection issue"
    assert candidate.evidence == (
        "evidence-1",
        "evidence-2",
        "evidence-3",
    )
    assert candidate.occurrence_count == 3
    assert candidate.confidence == 0.85
    assert candidate.status is ImprovementReviewStatus.PENDING_REVIEW
    assert candidate.created_at == 1_700_000_100.0
    assert candidate.reviewed_at is None


def test_next_question_maps_to_question_strategy():
    service = ImprovementCandidateService()

    pattern = _make_pattern(LearningComponent.NEXT_QUESTION)

    candidate = service.create_candidate(
        pattern,
        confidence=0.90,
        created_at=1_700_000_100.0,
    )

    assert candidate.improvement_type is ImprovementType.QUESTION_STRATEGY


def test_sentiment_maps_to_sentiment_analysis():
    service = ImprovementCandidateService()

    pattern = _make_pattern(LearningComponent.SENTIMENT_ANALYSIS)

    candidate = service.create_candidate(
        pattern,
        confidence=0.80,
        created_at=1_700_000_100.0,
    )

    assert candidate.improvement_type is ImprovementType.SENTIMENT_ANALYSIS


def test_estimation_maps_to_estimation_rule():
    service = ImprovementCandidateService()

    pattern = _make_pattern(LearningComponent.ESTIMATION)

    candidate = service.create_candidate(
        pattern,
        confidence=0.75,
        created_at=1_700_000_100.0,
    )

    assert candidate.improvement_type is ImprovementType.ESTIMATION_RULE


def test_general_maps_to_general_process():
    service = ImprovementCandidateService()

    pattern = _make_pattern(LearningComponent.GENERAL)

    candidate = service.create_candidate(
        pattern,
        confidence=0.70,
        created_at=1_700_000_100.0,
    )

    assert candidate.improvement_type is ImprovementType.GENERAL_PROCESS


def test_candidate_preserves_pattern_information():
    service = ImprovementCandidateService()

    pattern = _make_pattern()

    candidate = service.create_candidate(
        pattern,
        confidence=0.91,
        created_at=1_700_000_100.0,
    )

    assert candidate.description == pattern.description
    assert candidate.evidence == tuple(pattern.evidence_ids)
    assert candidate.occurrence_count == pattern.occurrence_count


def test_each_candidate_gets_a_unique_id():
    service = ImprovementCandidateService()

    pattern = _make_pattern()

    candidate_1 = service.create_candidate(
        pattern,
        confidence=0.80,
        created_at=1_700_000_100.0,
    )
    candidate_2 = service.create_candidate(
        pattern,
        confidence=0.80,
        created_at=1_700_000_100.0,
    )

    assert candidate_1.candidate_id != candidate_2.candidate_id
