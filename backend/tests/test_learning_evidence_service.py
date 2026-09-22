import pytest

from app.domain.learning_evidence import (
    EvidenceType,
    LearningComponent,
)
from app.domain.learning_evidence_repository import (
    InMemoryLearningEvidenceRepository,
)
from app.services.learning_evidence_service import (
    LearningEvidenceNotFoundError,
    LearningEvidenceService,
)


def create_service() -> LearningEvidenceService:
    repository = InMemoryLearningEvidenceRepository()
    return LearningEvidenceService(repository)


def test_service_records_and_retrieves_evidence():
    service = create_service()

    evidence = service.record(
        evidence_id="EVIDENCE_001",
        call_id="CALL_001",
        evidence_type=EvidenceType.AI_PREDICTION,
        component=LearningComponent.COMPLAINT_DETECTION,
        description="AI detected a communication complaint.",
        expected_value="Communication",
        actual_value="Communication",
        human_correction=None,
        created_at=100.0,
    )

    retrieved = service.get("EVIDENCE_001")

    assert retrieved == evidence
    assert retrieved.call_id == "CALL_001"


def test_service_supports_human_correction():
    service = create_service()

    evidence = service.record(
        evidence_id="EVIDENCE_002",
        call_id="CALL_002",
        evidence_type=EvidenceType.HUMAN_CORRECTION,
        component=LearningComponent.SENTIMENT_ANALYSIS,
        description="ICR corrected the sentiment.",
        expected_value="neutral",
        actual_value="positive",
        human_correction="positive",
        created_at=200.0,
    )

    assert evidence.human_correction == "positive"


def test_service_raises_error_for_unknown_evidence():
    service = create_service()

    with pytest.raises(
        LearningEvidenceNotFoundError,
        match="EVIDENCE_404",
    ):
        service.get("EVIDENCE_404")
