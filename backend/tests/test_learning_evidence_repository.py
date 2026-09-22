from app.domain.learning_evidence import (
    EvidenceType,
    LearningComponent,
    LearningEvidence,
)
from app.domain.learning_evidence_repository import (
    InMemoryLearningEvidenceRepository,
)


def create_evidence(evidence_id: str) -> LearningEvidence:
    return LearningEvidence(
        evidence_id=evidence_id,
        call_id="CALL_001",
        evidence_type=EvidenceType.AI_PREDICTION,
        component=LearningComponent.COMPLAINT_DETECTION,
        description="AI detected a complaint.",
        expected_value="Communication",
        actual_value="Communication",
        human_correction=None,
        created_at=100.0,
    )


def test_repository_saves_and_gets_evidence():
    repository = InMemoryLearningEvidenceRepository()
    evidence = create_evidence("EVIDENCE_001")

    repository.save(evidence)

    assert repository.get("EVIDENCE_001") == evidence


def test_repository_returns_none_for_unknown_evidence():
    repository = InMemoryLearningEvidenceRepository()

    assert repository.get("UNKNOWN") is None


def test_repository_replaces_existing_evidence_with_same_id():
    repository = InMemoryLearningEvidenceRepository()

    first = create_evidence("EVIDENCE_001")
    second = create_evidence("EVIDENCE_001")

    repository.save(first)
    repository.save(second)

    assert repository.get("EVIDENCE_001") == second