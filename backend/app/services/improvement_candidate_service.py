"""Service for creating improvement candidates from discovered patterns."""

import time
from uuid import uuid4

from app.domain.improvement_candidate import (
    ImprovementCandidate,
    ImprovementReviewStatus,
    ImprovementSpecification,
    ImprovementType,
)
from app.domain.learning_evidence import LearningComponent
from app.domain.learning_pattern import LearningPattern
from app.domain.improvement_candidate_repository import ImprovementCandidateRepository

class ImprovementCandidateService:
    """Creates reviewable improvement candidates from LearningPatterns.

    This service does not modify AI behaviour, access an LLM, or persist data.
    It only converts a discovered pattern into a human-reviewable candidate.
    """

    def __init__(self, repository: ImprovementCandidateRepository | None = None) -> None:
        self._repository = repository

    _COMPONENT_TO_IMPROVEMENT_TYPE = {
        LearningComponent.NEXT_QUESTION: ImprovementType.QUESTION_STRATEGY,
        LearningComponent.COMPLAINT_DETECTION: ImprovementType.COMPLAINT_DETECTION,
        LearningComponent.SENTIMENT_ANALYSIS: ImprovementType.SENTIMENT_ANALYSIS,
        LearningComponent.ESTIMATION: ImprovementType.ESTIMATION_RULE,
        LearningComponent.GENERAL: ImprovementType.GENERAL_PROCESS,
    }

    def create_candidate(
        self,
        pattern: LearningPattern,
        confidence: float,
        created_at: float | None = None,
    ) -> ImprovementCandidate:
        """Create a pending improvement candidate from a learning pattern.

        Confidence is supplied by the caller because LearningPattern itself
        does not contain a confidence value. This service must not invent or
        derive a confidence score from occurrence count.
        """

        improvement_type = self._get_improvement_type(pattern.component)

        timestamp = time.time() if created_at is None else created_at
        specification = self._build_specification(pattern)
        candidate = ImprovementCandidate(
            candidate_id=f"candidate-{uuid4()}",
            improvement_type=improvement_type,
            title=self._build_title(pattern),
            description=pattern.description,
            evidence=tuple(pattern.evidence_ids),
            occurrence_count=pattern.occurrence_count,
            confidence=confidence,
            status=ImprovementReviewStatus.PENDING_REVIEW,
            created_at=timestamp,
            specification=specification,
            
        )
        if self._repository is not None:
            self._repository.save(candidate)
        
        return candidate

    @classmethod
    def _get_improvement_type(
        cls,
        component: LearningComponent,
    ) -> ImprovementType:
        """Convert a learning component into an improvement type."""

        try:
            return cls._COMPONENT_TO_IMPROVEMENT_TYPE[component]
        except KeyError as exc:
            raise ValueError(
                f"No ImprovementType mapping exists for component: {component}"
            ) from exc

    @staticmethod
    def _build_specification(pattern: LearningPattern) -> ImprovementSpecification:
        """Derives the structured representation from the pattern's own
        description/suggested_improvement — no new data is invented here."""

        return ImprovementSpecification(
            component=pattern.component,
            current_behavior=pattern.description,
            proposed_behavior=pattern.suggested_improvement,
            reason=(
                f"Pattern recurred {pattern.occurrence_count} time(s), "
                "indicating this is not a one-off occurrence."
            ),
        )

    @staticmethod
    def _build_title(pattern: LearningPattern) -> str:
        """Create a concise human-readable title for the candidate."""

        return f"Improve {pattern.component.value.replace('_', ' ')}"
