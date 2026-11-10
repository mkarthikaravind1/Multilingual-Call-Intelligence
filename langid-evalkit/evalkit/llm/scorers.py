"""Task Scorers for LLM Evaluation (Complaints, Sentiment, Extensible)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def extract_json(raw_text: str) -> Tuple[Optional[Any], bool]:
    """Extract and parse JSON from text, tolerating markdown code fences.

    Returns:
        (parsed_json, is_valid_bool)
    """
    if not raw_text or not raw_text.strip():
        return None, False

    text = raw_text.strip()
    match = JSON_FENCE_PATTERN.search(text)
    candidate = match.group(1).strip() if match else text

    # Attempt direct parse
    try:
        return json.loads(candidate), True
    except json.JSONDecodeError:
        pass

    # Secondary heuristic: look for outermost brackets
    for start_char, end_char in [("[", "]"), ("{", "}")]:
        start = candidate.find(start_char)
        end = candidate.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1]), True
            except json.JSONDecodeError:
                pass

    return None, False


@dataclass
class TaskScoreResult:
    is_valid_json: bool
    prediction: Any
    expected: Any
    metrics: Dict[str, float] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)


class BaseTaskScorer(ABC):
    """Abstract base class for LLM evaluation task scorers."""

    @abstractmethod
    def score(self, raw_output: str, expected: Any) -> TaskScoreResult:
        """Evaluate model output against expected ground truth."""
        pass


class ComplaintsScorer(BaseTaskScorer):
    """Scorer for the 'complaints' extraction task."""

    ALLOWED_CATEGORIES = {
        "cost",
        "hygiene",
        "hospitality",
        "service quality",
        "turnaround time",
        "communication",
        "parts availability",
        "staff behaviour",
        "documentation",
        "other",
    }

    # Canonical capitalizations
    CANONICAL_MAP = {
        "cost": "Cost",
        "hygiene": "Hygiene",
        "hospitality": "Hospitality",
        "service quality": "Service Quality",
        "turnaround time": "Turnaround Time",
        "communication": "Communication",
        "parts availability": "Parts Availability",
        "staff behaviour": "Staff Behaviour",
        "staff behavior": "Staff Behaviour",
        "documentation": "Documentation",
        "other": "Other",
    }

    def score(self, raw_output: str, expected: Any) -> TaskScoreResult:
        data, is_valid = extract_json(raw_output)
        if not isinstance(expected, (list, set, tuple)):
            expected = [expected] if expected else []

        expected_norm: Set[str] = {
            self.CANONICAL_MAP.get(str(cat).strip().lower(), str(cat)) for cat in expected
        }

        if not is_valid or not isinstance(data, list):
            return TaskScoreResult(
                is_valid_json=is_valid,
                prediction=[],
                expected=sorted(list(expected_norm)),
                metrics={
                    "precision": 0.0,
                    "recall": 0.0,
                    "exact_match": 0.0,
                    "is_multi_category": 1.0 if len(expected_norm) > 1 else 0.0,
                    "multi_category_exact_match": 0.0 if len(expected_norm) > 1 else 1.0,
                },
                details={"error": "Malformed JSON or not a list"},
            )

        pred_categories: Set[str] = set()
        for item in data:
            if isinstance(item, dict) and "category" in item:
                cat_raw = str(item["category"]).strip().lower()
                canonical = self.CANONICAL_MAP.get(cat_raw, item["category"])
                pred_categories.add(canonical)

        tp = len(pred_categories.intersection(expected_norm))
        fp = len(pred_categories - expected_norm)
        fn = len(expected_norm - pred_categories)

        precision = (tp / (tp + fp)) if (tp + fp) > 0 else (1.0 if not expected_norm and not pred_categories else 0.0)
        recall = (tp / (tp + fn)) if (tp + fn) > 0 else 1.0
        exact_match = 1.0 if pred_categories == expected_norm else 0.0
        is_multi = len(expected_norm) > 1

        return TaskScoreResult(
            is_valid_json=True,
            prediction=sorted(list(pred_categories)),
            expected=sorted(list(expected_norm)),
            metrics={
                "precision": precision,
                "recall": recall,
                "exact_match": exact_match,
                "is_multi_category": 1.0 if is_multi else 0.0,
                "multi_category_exact_match": exact_match if is_multi else 1.0,
            },
            details={"raw_parsed": data},
        )


class SentimentScorer(BaseTaskScorer):
    """Scorer for the 'sentiment' classification task."""

    ALLOWED_LABELS = {"POSITIVE", "NEUTRAL", "NEGATIVE", "FRUSTRATED", "ESCALATING"}

    def score(self, raw_output: str, expected: Any) -> TaskScoreResult:
        data, is_valid = extract_json(raw_output)
        expected_norm = str(expected).strip().upper()

        if not is_valid or not isinstance(data, dict):
            return TaskScoreResult(
                is_valid_json=is_valid,
                prediction=None,
                expected=expected_norm,
                metrics={"accuracy": 0.0},
                details={"error": "Malformed JSON or not a dict"},
            )

        label_raw = str(data.get("label", "")).strip().upper()
        accuracy = 1.0 if label_raw == expected_norm else 0.0

        return TaskScoreResult(
            is_valid_json=True,
            prediction=label_raw,
            expected=expected_norm,
            metrics={"accuracy": accuracy},
            details={"raw_parsed": data},
        )


SCORER_REGISTRY: Dict[str, BaseTaskScorer] = {
    "complaints": ComplaintsScorer(),
    "sentiment": SentimentScorer(),
}


def register_scorer(task_name: str, scorer: BaseTaskScorer):
    """Register a custom scorer for a new task."""
    SCORER_REGISTRY[task_name] = scorer

