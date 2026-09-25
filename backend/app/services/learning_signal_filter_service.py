from collections.abc import Iterable

from app.domain.learning_evidence import EvidenceType, LearningEvidence

_COMPARABLE_TYPES = frozenset({EvidenceType.AI_PREDICTION, EvidenceType.HUMAN_CORRECTION})


def _normalise(value: str) -> str:
    return value.strip().casefold()


class LearningSignalFilterService:
    def is_signal(self, evidence: LearningEvidence) -> bool:
        reference = evidence.human_correction
        if reference is None and evidence.evidence_type in _COMPARABLE_TYPES:
            reference = evidence.expected_value
        if reference is None:
            return False
        if evidence.actual_value is None:
            return True
        return _normalise(reference) != _normalise(evidence.actual_value)

    def filter(self, records: Iterable[LearningEvidence]) -> list[LearningEvidence]:
        return [record for record in records if self.is_signal(record)]