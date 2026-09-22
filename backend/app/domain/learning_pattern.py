"""Domain model representing a repeated learning pattern discovered from LearningEvidence."""

from dataclasses import dataclass
from numbers import Real

from app.domain.learning_evidence import LearningComponent


def _is_non_empty_str(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


@dataclass(frozen=True)
class LearningPattern:
    """A repeated pattern discovered across one or more LearningEvidence records."""

    pattern_id: str
    component: LearningComponent
    description: str
    occurrence_count: int
    evidence_ids: list[str]
    suggested_improvement: str
    created_at: float

    def __post_init__(self) -> None:
        if not _is_non_empty_str(self.pattern_id):
            raise ValueError("pattern_id must be a non-empty string")

        if not isinstance(self.component, LearningComponent):
            raise ValueError("component must be a valid LearningComponent")

        if not _is_non_empty_str(self.description):
            raise ValueError("description must be a non-empty string")

        if isinstance(self.occurrence_count, bool) or not isinstance(self.occurrence_count, int):
            raise ValueError("occurrence_count must be an integer >= 1")
        if self.occurrence_count < 1:
            raise ValueError("occurrence_count must be an integer >= 1")

        if not isinstance(self.evidence_ids, list) or len(self.evidence_ids) == 0:
            raise ValueError("evidence_ids must be a non-empty list of non-empty strings")
        if not all(_is_non_empty_str(evidence_id) for evidence_id in self.evidence_ids):
            raise ValueError("evidence_ids must be a non-empty list of non-empty strings")

        if not _is_non_empty_str(self.suggested_improvement):
            raise ValueError("suggested_improvement must be a non-empty string")

        if isinstance(self.created_at, bool) or not isinstance(self.created_at, Real):
            raise ValueError("created_at must be numeric and >= 0")
        if self.created_at < 0:
            raise ValueError("created_at must be numeric and >= 0")