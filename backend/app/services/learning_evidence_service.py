from app.domain.learning_evidence import (
    EvidenceType,
    LearningComponent,
    LearningEvidence,
)
from app.domain.learning_evidence_repository import LearningEvidenceRepository


class LearningEvidenceNotFoundError(Exception):
    pass


class LearningEvidenceService:
    def __init__(self, repository: LearningEvidenceRepository) -> None:
        self._repository = repository

    def record(
        self,
        evidence_id: str,
        call_id: str,
        evidence_type: EvidenceType,
        component: LearningComponent,
        description: str,
        expected_value: str | None,
        actual_value: str | None,
        human_correction: str | None,
        created_at: float,
    ) -> LearningEvidence:
        evidence = LearningEvidence(
            evidence_id=evidence_id,
            call_id=call_id,
            evidence_type=evidence_type,
            component=component,
            description=description,
            expected_value=expected_value,
            actual_value=actual_value,
            human_correction=human_correction,
            created_at=created_at,
        )

        self._repository.save(evidence)
        return evidence

    def get(self, evidence_id: str) -> LearningEvidence:
        evidence = self._repository.get(evidence_id)

        if evidence is None:
            raise LearningEvidenceNotFoundError(
                f"Learning evidence not found: {evidence_id}"
            )

        return evidence
