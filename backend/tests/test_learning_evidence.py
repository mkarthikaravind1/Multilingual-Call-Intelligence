import pytest

from app.domain.learning_evidence import (
    EvidenceType,
    LearningComponent,
    LearningEvidence,
)


def test_learning_evidence_can_be_created():
    evidence = LearningEvidence(
        evidence_id="evidence_001",
        call_id="CALL_001",
        evidence_type=EvidenceType.AI_PREDICTION,
        component=LearningComponent.COMPLAINT_DETECTION,
        description="AI detected a communication complaint.",
        expected_value="Communication",
        actual_value="Communication",
        human_correction=None,
        created_at=100.0,
    )

    assert evidence.evidence_id == "evidence_001"
    assert evidence.call_id == "CALL_001"
    assert evidence.evidence_type == EvidenceType.AI_PREDICTION
    assert evidence.component == LearningComponent.COMPLAINT_DETECTION


def test_learning_evidence_supports_human_correction():
    evidence = LearningEvidence(
        evidence_id="evidence_002",
        call_id="CALL_002",
        evidence_type=EvidenceType.HUMAN_CORRECTION,
        component=LearningComponent.SENTIMENT_ANALYSIS,
        description="ICR corrected the detected sentiment.",
        expected_value="neutral",
        actual_value="positive",
        human_correction="positive",
        created_at=200.0,
    )

    assert evidence.human_correction == "positive"


def test_learning_evidence_allows_optional_values():
    evidence = LearningEvidence(
        evidence_id="evidence_003",
        call_id="CALL_003",
        evidence_type=EvidenceType.OUTCOME,
        component=LearningComponent.ESTIMATION,
        description="Customer accepted the estimate.",
        expected_value=None,
        actual_value="accepted",
        human_correction=None,
        created_at=300.0,
    )

    assert evidence.expected_value is None
    assert evidence.human_correction is None


def test_empty_evidence_id_is_rejected():
    with pytest.raises(ValueError, match="evidence_id"):
        LearningEvidence(
            evidence_id="",
            call_id="CALL_001",
            evidence_type=EvidenceType.AI_PREDICTION,
            component=LearningComponent.GENERAL,
            description="Test evidence.",
            expected_value=None,
            actual_value=None,
            human_correction=None,
            created_at=100.0,
        )


def test_empty_call_id_is_rejected():
    with pytest.raises(ValueError, match="call_id"):
        LearningEvidence(
            evidence_id="evidence_001",
            call_id="",
            evidence_type=EvidenceType.AI_PREDICTION,
            component=LearningComponent.GENERAL,
            description="Test evidence.",
            expected_value=None,
            actual_value=None,
            human_correction=None,
            created_at=100.0,
        )


def test_empty_description_is_rejected():
    with pytest.raises(ValueError, match="description"):
        LearningEvidence(
            evidence_id="evidence_001",
            call_id="CALL_001",
            evidence_type=EvidenceType.AI_PREDICTION,
            component=LearningComponent.GENERAL,
            description="",
            expected_value=None,
            actual_value=None,
            human_correction=None,
            created_at=100.0,
        )


def test_negative_created_at_is_rejected():
    with pytest.raises(ValueError, match="created_at"):
        LearningEvidence(
            evidence_id="evidence_001",
            call_id="CALL_001",
            evidence_type=EvidenceType.AI_PREDICTION,
            component=LearningComponent.GENERAL,
            description="Test evidence.",
            expected_value=None,
            actual_value=None,
            human_correction=None,
            created_at=-1.0,
        )


def test_learning_evidence_is_immutable():
    evidence = LearningEvidence(
        evidence_id="evidence_001",
        call_id="CALL_001",
        evidence_type=EvidenceType.AI_PREDICTION,
        component=LearningComponent.GENERAL,
        description="Test evidence.",
        expected_value=None,
        actual_value=None,
        human_correction=None,
        created_at=100.0,
    )

    with pytest.raises(AttributeError):
        evidence.description = "Changed" # type: ignore