"""Unit tests for evalkit.llm: LLM evaluation and scoring."""

import json
import pytest

from evalkit.llm.client import MockLLMClient
from evalkit.llm.scorers import (
    BaseTaskScorer,
    ComplaintsScorer,
    SentimentScorer,
    TaskScoreResult,
    extract_json,
    register_scorer,
    SCORER_REGISTRY,
)
from evalkit.llm.__main__ import (
    compute_side_by_side_agreement,
    evaluate_dataset,
    summarize_evaluation,
)


def test_extract_json():
    # Markdown code fence
    fence_text = "Here is the result:\n```json\n[{\"category\": \"Cost\"}]\n```\nHope that helps!"
    parsed, is_valid = extract_json(fence_text)
    assert is_valid is True
    assert parsed == [{"category": "Cost"}]

    # Bare JSON
    bare_text = '{"label": "NEGATIVE", "confidence": 0.8}'
    parsed, is_valid = extract_json(bare_text)
    assert is_valid is True
    assert parsed["label"] == "NEGATIVE"

    # Malformed JSON
    bad_text = "Sorry, I cannot process this call."
    parsed, is_valid = extract_json(bad_text)
    assert is_valid is False
    assert parsed is None


def test_complaints_scorer():
    scorer = ComplaintsScorer()

    # Exact match single category
    raw = '[{"category": "Cost", "confidence": 0.9, "evidence": "Bill high"}]'
    res = scorer.score(raw, ["Cost"])
    assert res.is_valid_json is True
    assert res.metrics["exact_match"] == 1.0
    assert res.metrics["precision"] == 1.0
    assert res.metrics["recall"] == 1.0

    # Multi-category call
    raw_multi = '[{"category": "Cost"}, {"category": "Turnaround Time"}]'
    res_multi = scorer.score(raw_multi, ["Cost", "Turnaround Time"])
    assert res_multi.metrics["exact_match"] == 1.0
    assert res_multi.metrics["is_multi_category"] == 1.0
    assert res_multi.metrics["multi_category_exact_match"] == 1.0

    # Partial match
    raw_partial = '[{"category": "Cost"}]'
    res_part = scorer.score(raw_partial, ["Cost", "Turnaround Time"])
    assert res_part.metrics["exact_match"] == 0.0
    assert res_part.metrics["precision"] == 1.0
    assert res_part.metrics["recall"] == 0.5
    assert res_part.metrics["multi_category_exact_match"] == 0.0


def test_sentiment_scorer():
    scorer = SentimentScorer()

    raw = '{"label": "FRUSTRATED", "confidence": 0.85, "evidence": "Customer shouting"}'
    res = scorer.score(raw, "FRUSTRATED")
    assert res.is_valid_json is True
    assert res.metrics["accuracy"] == 1.0

    res_wrong = scorer.score(raw, "POSITIVE")
    assert res_wrong.metrics["accuracy"] == 0.0


def test_custom_scorer_extensibility():
    class QuestionScorer(BaseTaskScorer):
        def score(self, raw_output: str, expected: any) -> TaskScoreResult:
            data, is_valid = extract_json(raw_output)
            acc = 1.0 if is_valid and isinstance(data, dict) and "question" in data else 0.0
            return TaskScoreResult(
                is_valid_json=is_valid,
                prediction=data,
                expected=expected,
                metrics={"has_question": acc},
            )

    register_scorer("suggested_questions", QuestionScorer())
    assert "suggested_questions" in SCORER_REGISTRY


def test_end_to_end_mock_evaluation(tmp_path):
    dataset_path = "evalkit/llm/sample_data.jsonl"
    client = MockLLMClient()
    results = evaluate_dataset(client, dataset_path)
    assert len(results) == 20

    summary = summarize_evaluation(results)
    assert summary["total_calls"] == 20
    assert summary["valid_json_share"] == 1.0
    assert "complaints" in summary
    assert "sentiment" in summary


def test_side_by_side_agreement():
    results_a = [
        {"id": "1", "task": "sentiment", "prediction": "NEGATIVE"},
        {"id": "2", "task": "complaints", "prediction": ["Cost"]},
    ]
    results_b = [
        {"id": "1", "task": "sentiment", "prediction": "NEGATIVE"},
        {"id": "2", "task": "complaints", "prediction": ["Service Quality"]},
    ]
    agreement = compute_side_by_side_agreement(results_a, results_b)
    assert agreement["sentiment"] == 1.0
    assert agreement["complaints"] == 0.0
    assert agreement["overall"] == 0.5

