"""Deterministic Pattern Discovery service.

Groups injected LearningEvidence records by (component, description) and turns
any group with 2+ matching records into a LearningPattern. No LLM involved —
purely rule-based grouping and string templating.
"""

import time
from collections import defaultdict
from typing import Sequence
from uuid import uuid4

from app.domain.learning_evidence import LearningComponent, LearningEvidence
from app.domain.learning_pattern import LearningPattern

MIN_OCCURRENCES_FOR_PATTERN = 2


class PatternDiscoveryService:
    """Discovers repeated LearningPatterns from a fixed set of LearningEvidence.

    Evidence is provided via constructor injection — this service never talks
    to a repository or any other data source directly.
    """

    def __init__(self, evidence_records: Sequence[LearningEvidence]):
        self._evidence_records = list(evidence_records)

    def discover_patterns(self) -> list[LearningPattern]:
        """Return one LearningPattern per (component, description) group that
        has at least MIN_OCCURRENCES_FOR_PATTERN matching evidence records.
        Returns an empty list when no such group exists.
        """
        grouped_evidence = self._group_matching_evidence()

        patterns: list[LearningPattern] = []
        for (component, description), evidences in grouped_evidence.items():
            if len(evidences) >= MIN_OCCURRENCES_FOR_PATTERN:
                patterns.append(self._build_pattern(component, description, evidences))

        return patterns

    def _group_matching_evidence(
        self,
    ) -> dict[tuple[LearningComponent, str], list[LearningEvidence]]:
        """Group evidence first by component, then by matching description.

        Two evidence records are considered the "same" repeated pattern when
        they belong to the same component and have the same description
        (after trimming incidental whitespace).
        """
        groups: dict[tuple[LearningComponent, str], list[LearningEvidence]] = defaultdict(list)

        for evidence in self._evidence_records:
            normalized_description = self._normalize_description(evidence.description)
            key = (evidence.component, normalized_description)
            groups[key].append(evidence)

        return groups

    @staticmethod
    def _normalize_description(description: str) -> str:
        # Kept intentionally simple: exact match after trimming incidental
        # leading/trailing whitespace. No fuzzy/semantic matching yet.
        return description.strip()

    @staticmethod
    def _build_pattern(
        component: LearningComponent,
        normalized_description: str,
        evidences: list[LearningEvidence],
    ) -> LearningPattern:
        occurrence_count = len(evidences)
        evidence_ids = [evidence.evidence_id for evidence in evidences]
        # Keep the original (non-normalized) wording for anything user-facing.
        original_description = evidences[0].description.strip()

        pattern_description = (
            f"Recurring issue detected in {component.value}: "
            f"'{original_description}' observed {occurrence_count} times."
        )
        suggested_improvement = (
            f"Investigate and address the recurring '{original_description}' issue "
            f"in {component.value}; consider retraining or adjusting logic for this case."
        )

        return LearningPattern(
            pattern_id=f"pattern-{uuid4()}",
            component=component,
            description=pattern_description,
            occurrence_count=occurrence_count,
            evidence_ids=evidence_ids,
            suggested_improvement=suggested_improvement,
            created_at=time.time(),
        )