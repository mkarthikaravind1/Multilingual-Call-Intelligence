from abc import ABC, abstractmethod

from app.domain.learning_evidence import LearningEvidence


class LearningEvidenceRepository(ABC):
    @abstractmethod
    def save(self, evidence: LearningEvidence) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, evidence_id: str) -> LearningEvidence | None:
        raise NotImplementedError


class InMemoryLearningEvidenceRepository(LearningEvidenceRepository):
    def __init__(self) -> None:
        self._evidence: dict[str, LearningEvidence] = {}

    def save(self, evidence: LearningEvidence) -> None:
        self._evidence[evidence.evidence_id] = evidence

    def get(self, evidence_id: str) -> LearningEvidence | None:
        return self._evidence.get(evidence_id)
