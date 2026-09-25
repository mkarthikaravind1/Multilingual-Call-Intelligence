from dataclasses import dataclass

from app.domain.improvement_candidate import ImprovementSpecification
from app.domain.learning_evidence import LearningComponent


@dataclass(frozen=True)
class RuntimeImprovementContext:
    """Read-only projection of an ActiveImprovement for AI components.
    Carries no repository/persistence concepts."""

    improvement_id: str
    candidate_id: str
    component: LearningComponent
    specification: ImprovementSpecification

    def __post_init__(self) -> None:
        if not self.improvement_id.strip():
            raise ValueError("improvement_id must not be empty.")
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must not be empty.")
        if not isinstance(self.component, LearningComponent):
            raise TypeError(
                f"component must be a LearningComponent, got {type(self.component).__name__}."
            )
        if not isinstance(self.specification, ImprovementSpecification):
            raise TypeError(
                "specification must be an ImprovementSpecification, "
                f"got {type(self.specification).__name__}."
            )