import dataclasses

import pytest

from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
)


@pytest.mark.parametrize(
    "label, confidence, evidence",
    [
        (SentimentLabel.POSITIVE, 0.92, "Customer thanked the ICR and praised the quick service."),
        (SentimentLabel.NEUTRAL, 0.60, "Customer only asked factual questions about the booking."),
        (SentimentLabel.NEGATIVE, 0.85, "Customer complained about repeated delays and high cost."),
    ],
)
def test_valid_sentiment_result(label, confidence, evidence):
    result = SentimentResult(label=label, confidence=confidence, evidence=evidence)

    assert result.label is label
    assert result.confidence == confidence
    assert result.evidence == evidence


@pytest.mark.parametrize("confidence", [0.0, 1.0, 0, 1])
def test_confidence_boundaries_are_accepted(confidence):
    result = SentimentResult(SentimentLabel.NEUTRAL, confidence, "Boundary value.")

    assert result.confidence == confidence


@pytest.mark.parametrize("confidence", [-0.01, -1.0])
def test_confidence_below_zero_is_rejected(confidence):
    with pytest.raises(ValueError, match="confidence"):
        SentimentResult(SentimentLabel.POSITIVE, confidence, "Some evidence.")


@pytest.mark.parametrize("confidence", [1.01, 2.0, float("nan")])
def test_confidence_above_one_is_rejected(confidence):
    with pytest.raises(ValueError, match="confidence"):
        SentimentResult(SentimentLabel.POSITIVE, confidence, "Some evidence.")


@pytest.mark.parametrize("confidence", [True, False, "0.5", None, [0.5]])
def test_invalid_confidence_type_is_rejected(confidence):
    with pytest.raises(TypeError, match="confidence"):
        SentimentResult(SentimentLabel.POSITIVE, confidence, "Some evidence.")


@pytest.mark.parametrize("evidence", ["", "   ", "\n\t"])
def test_empty_evidence_is_rejected(evidence):
    with pytest.raises(ValueError, match="evidence"):
        SentimentResult(SentimentLabel.NEGATIVE, 0.8, evidence)


@pytest.mark.parametrize("label", ["POSITIVE", "positive", None, 1])
def test_invalid_label_is_rejected(label):
    with pytest.raises(TypeError, match="label"):
        SentimentResult(label, 0.8, "Some evidence.")


def test_sentiment_result_is_immutable():
    result = SentimentResult(SentimentLabel.NEUTRAL, 0.5, "Some evidence.")

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.confidence = 0.9 #type: ignore

def test_abstract_provider_cannot_be_instantiated():
    with pytest.raises(TypeError):
        SentimentAnalysisProvider() #type: ignore