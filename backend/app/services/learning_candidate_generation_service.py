from collections.abc import Callable, Sequence

from app.domain.improvement_candidate import ImprovementCandidate
from app.domain.learning_pattern import LearningPattern
from app.services.improvement_candidate_service import ImprovementCandidateService

DEFAULT_CANDIDATE_CONFIDENCE = 0.5


def _default_confidence(pattern: LearningPattern) -> float:
    return DEFAULT_CANDIDATE_CONFIDENCE


class LearningCandidateGenerationService:
    def __init__(
        self,
        candidate_service: ImprovementCandidateService,
        confidence_provider: Callable[[LearningPattern], float] = _default_confidence,
    ) -> None:
        self._candidate_service = candidate_service
        self._confidence_provider = confidence_provider

    def generate(self, patterns: Sequence[LearningPattern]) -> list[ImprovementCandidate]:
        if not all(isinstance(pattern, LearningPattern) for pattern in patterns):
            raise TypeError("patterns must contain only LearningPattern objects.")

        return [
            self._candidate_service.create_candidate(
                pattern, confidence=self._confidence_provider(pattern)
            )
            for pattern in patterns
        ]