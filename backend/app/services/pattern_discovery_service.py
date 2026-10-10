"""Deterministic Pattern Discovery service.

Groups injected LearningEvidence records by (component, description) and turns
a group into a LearningPattern once it is more than a coincidence: enough
matching records, from more than one call, and often enough compared with how
often the AI gave that output at all. No LLM involved — purely rule-based
grouping and string templating.
"""

import re
import time
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Sequence
from uuid import uuid4

from app.domain.learning_evidence import LearningComponent, LearningEvidence
from app.domain.learning_pattern import LearningPattern

MIN_OCCURRENCES_FOR_PATTERN = 3
# Text typed by a reviewer ends up in the AI's instructions once approved:
# keep it to one short line.
_MAX_QUOTED_LENGTH = 200

# (component, the AI's output, case-folded) -> on how many calls the AI gave it.
OutputCalls = Mapping[tuple[LearningComponent, str], int]


@dataclass(frozen=True)
class PatternRules:
    """When matching corrections count as a pattern worth a reviewer's time."""

    # At least this many matching corrections...
    min_occurrences: int = MIN_OCCURRENCES_FOR_PATTERN
    # ...from at least this many different calls...
    min_calls: int = 2
    # ...making up at least this share of the calls on which the AI gave
    # that output (checked only when those counts are known).
    min_correction_rate: float = 0.3


def output_key(component: LearningComponent, value: str | None) -> tuple[LearningComponent, str]:
    return component, (value or "").strip().casefold()


class PatternDiscoveryService:
    """Discovers repeated LearningPatterns from a fixed set of LearningEvidence.

    Evidence is provided via constructor injection — this service never talks
    to a repository or any other data source directly.
    """

    def __init__(
        self,
        evidence_records: Sequence[LearningEvidence],
        rules: PatternRules | None = None,
        output_calls: OutputCalls | None = None,
    ):
        self._evidence_records = list(evidence_records)
        self._rules = rules or PatternRules()
        # None: not known, so the correction rate is not checked.
        self._output_calls = output_calls

    def discover_patterns(self) -> list[LearningPattern]:
        """Return one LearningPattern per (component, description) group that
        meets the rules. Returns an empty list when no such group exists.
        """
        grouped_evidence = self._group_matching_evidence()

        patterns: list[LearningPattern] = []
        for (component, _), evidences in grouped_evidence.items():
            if len(evidences) < self._rules.min_occurrences:
                continue
            corrected_calls = len({evidence.call_id for evidence in evidences})
            if corrected_calls < self._rules.min_calls:
                continue
            output_calls = self._calls_with_output(component, evidences, corrected_calls)
            if (
                output_calls is not None
                and corrected_calls / output_calls < self._rules.min_correction_rate
            ):
                continue
            patterns.append(
                self._build_pattern(component, evidences, corrected_calls, output_calls)
            )

        return patterns

    def _calls_with_output(
        self,
        component: LearningComponent,
        evidences: list[LearningEvidence],
        corrected_calls: int,
    ) -> int | None:
        if self._output_calls is None:
            return None
        counted = self._output_calls.get(output_key(component, evidences[0].actual_value), 0)
        # Never fewer than the calls it was corrected on.
        return max(counted, corrected_calls)

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
        evidences: list[LearningEvidence],
        corrected_calls: int,
        output_calls: int | None,
    ) -> LearningPattern:
        first = evidences[0]
        how_often = _how_often(corrected_calls, output_calls)
        corrected_to = first.human_correction or first.expected_value

        if first.actual_value is None or corrected_to is None:
            # Evidence that does not say what was changed to what.
            wording = first.description.strip()
            pattern_description = f"Reviewers flagged '{wording}' in {component.value} {how_often}."
            suggested_improvement = (
                f"Reviewers flagged this {how_often}: {_quoted(wording)}. Take extra care "
                "in similar cases."
            )
        else:
            actual, corrected = _quoted(first.actual_value), _quoted(corrected_to)
            pattern_description = f"Reviewers corrected {actual} to {corrected} {how_often}."
            suggested_improvement = _instruction(component, actual, corrected, how_often)

        return LearningPattern(
            pattern_id=f"pattern-{uuid4()}",
            component=component,
            description=pattern_description,
            occurrence_count=len(evidences),
            evidence_ids=[evidence.evidence_id for evidence in evidences],
            suggested_improvement=suggested_improvement,
            created_at=time.time(),
        )


def _how_often(corrected_calls: int, output_calls: int | None) -> str:
    if output_calls is None:
        return f"on {corrected_calls} calls"
    share = round(100 * corrected_calls / output_calls)
    return f"on {corrected_calls} of the {output_calls} calls where the AI gave it ({share}%)"


def _quoted(value: str) -> str:
    """The value as one short quoted line."""
    text = re.sub(r"\s+", " ", value).strip().replace('"', "'")
    if len(text) > _MAX_QUOTED_LENGTH:
        text = text[: _MAX_QUOTED_LENGTH - 1].rstrip() + "…"
    return f'"{text}"'


def _instruction(
    component: LearningComponent, actual: str, corrected: str, how_often: str
) -> str:
    """What the AI is told once a reviewer approves the pattern: what to do
    differently, and how strong the evidence is."""
    if component is LearningComponent.COMPLAINT_DETECTION:
        if corrected.strip('"').casefold() == "no complaint":
            return (
                f"Report the complaint category {actual} only when the customer clearly "
                f"raises it themselves: reviewers found it was not a complaint {how_often}."
            )
        return (
            f"Before reporting the complaint category {actual}, check whether the customer "
            f"is really describing {corrected}: reviewers changed it {how_often}."
        )
    if component is LearningComponent.SENTIMENT_ANALYSIS:
        return (
            f"Before judging the customer's tone as {actual}, check whether it is really "
            f"{corrected}: reviewers changed it {how_often}."
        )
    if component is LearningComponent.NEXT_QUESTION:
        return (
            f"Where you would suggest the question {actual}, reviewers preferred "
            f"{corrected} ({how_often})."
        )
    return f"Reviewers corrected {actual} to {corrected} {how_often}; take that into account."
