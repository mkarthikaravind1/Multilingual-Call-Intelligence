import dataclasses
import logging
import threading
from collections.abc import Callable, Sequence

from app.domain.improvement_candidate import ImprovementCandidate, ImprovementReviewStatus
from app.domain.improvement_candidate_repository import ImprovementCandidateRepository
from app.domain.learning_evidence import LearningEvidence
from app.domain.learning_pattern import LearningPattern
from app.services.improvement_candidate_service import ImprovementCandidateService
from app.services.pattern_discovery_service import (
    OutputCalls,
    PatternDiscoveryService,
    PatternRules,
)

logger = logging.getLogger(__name__)

DEFAULT_CANDIDATE_CONFIDENCE = 0.5


def _default_confidence(pattern: LearningPattern) -> float:
    return DEFAULT_CANDIDATE_CONFIDENCE


class LearningCandidateGenerationService:
    def __init__(
        self,
        candidate_service: ImprovementCandidateService,
        confidence_provider: Callable[[LearningPattern], float] = _default_confidence,
        repository: ImprovementCandidateRepository | None = None,
        rules: PatternRules | None = None,
    ) -> None:
        # When matching corrections are worth proposing to a reviewer.
        self._rules = rules or PatternRules()
        self._candidate_service = candidate_service
        self._confidence_provider = confidence_provider
        self._repository = repository
        self._refresh_lock = threading.Lock()

    def generate(self, patterns: Sequence[LearningPattern]) -> list[ImprovementCandidate]:
        if not all(isinstance(pattern, LearningPattern) for pattern in patterns):
            raise TypeError("patterns must contain only LearningPattern objects.")

        return [
            self._candidate_service.create_candidate(
                pattern, confidence=self._confidence_provider(pattern)
            )
            for pattern in patterns
        ]

    def refresh(
        self, signals: Sequence[LearningEvidence], output_calls: OutputCalls | None = None
    ) -> list[ImprovementCandidate]:
        """Bring the stored candidates in line with the patterns in `signals`.
        output_calls: on how many calls the AI gave each output, which a
        pattern's corrections are compared with (None: not compared).

        A pattern keeps at most one PENDING_REVIEW candidate, refreshed as new
        evidence arrives. Evidence already covered by a reviewed (approved or
        rejected) candidate is not proposed again; a new candidate appears only
        once enough new evidence has accumulated. Evidence records belong to
        exactly one pattern, so a shared evidence id identifies the pattern a
        candidate was made from. Returns the candidates created or updated.
        """
        if self._repository is None:
            raise RuntimeError("refresh() requires a candidate repository.")

        with self._refresh_lock:
            candidates = self._repository.list_all()
            changed: list[ImprovementCandidate] = []
            patterns = PatternDiscoveryService(
                signals, self._rules, output_calls
            ).discover_patterns()
            for pattern in patterns:
                try:
                    candidate = self._refresh_pattern(
                        pattern, signals, candidates, output_calls
                    )
                except ValueError:
                    # e.g. a component with no improvement type; never fatal.
                    logger.exception(
                        "Skipping learning pattern for %s", pattern.component.value
                    )
                    continue
                if candidate is not None:
                    self._repository.save(candidate)
                    changed.append(candidate)
            return changed

    def _refresh_pattern(
        self,
        pattern: LearningPattern,
        signals: Sequence[LearningEvidence],
        candidates: Sequence[ImprovementCandidate],
        output_calls: OutputCalls | None = None,
    ) -> ImprovementCandidate | None:
        pattern_ids = set(pattern.evidence_ids)
        related = [c for c in candidates if pattern_ids.intersection(c.evidence)]
        pending = next(
            (c for c in related if c.status is ImprovementReviewStatus.PENDING_REVIEW),
            None,
        )
        reviewed_ids = {
            evidence_id
            for c in related
            if c.status is not ImprovementReviewStatus.PENDING_REVIEW
            for evidence_id in c.evidence
        }
        fresh_ids = pattern_ids - reviewed_ids
        if len(fresh_ids) < self._rules.min_occurrences:
            return None
        if pending is not None and set(pending.evidence) == fresh_ids:
            return None

        # Rebuild the pattern from the unreviewed evidence only, so its
        # description and count describe what the reviewer has not yet
        # seen. That evidence has to meet the rules by itself.
        fresh_patterns = PatternDiscoveryService(
            [e for e in signals if e.evidence_id in fresh_ids], self._rules, output_calls
        ).discover_patterns()
        if not fresh_patterns:
            return None
        fresh_pattern = fresh_patterns[0]
        proposal = ImprovementCandidateService().create_candidate(
            fresh_pattern, confidence=self._confidence_provider(fresh_pattern)
        )
        if pending is None:
            return proposal
        return dataclasses.replace(
            pending,
            description=proposal.description,
            evidence=proposal.evidence,
            occurrence_count=proposal.occurrence_count,
            specification=proposal.specification,
        )
