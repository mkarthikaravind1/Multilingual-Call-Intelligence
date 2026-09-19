import pytest

from app.ai.complaint.provider import (
    ComplaintDetectionProvider,
    ComplaintDetectionResult,
)
from app.core.constants import COMPLAINT_CATEGORIES
from app.domain.conversation import Conversation


class FakeComplaintProvider(ComplaintDetectionProvider):
    def detect(self, conversation: Conversation) -> list[ComplaintDetectionResult]:
        return [
            ComplaintDetectionResult("Cost", 0.9, "The bill was too high."),
            ComplaintDetectionResult("Turnaround Time", 0.7, "It took a week."),
        ]


def test_valid_result():
    result = ComplaintDetectionResult(
        category="Cost", confidence=0.9, evidence="The bill was too high."
    )

    assert result.category == "Cost"
    assert result.confidence == 0.9
    assert result.evidence == "The bill was too high."


@pytest.mark.parametrize("category", COMPLAINT_CATEGORIES)
def test_every_configured_category_is_accepted(category):
    assert ComplaintDetectionResult(category, 0.5, "evidence").category == category


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_confidence_boundaries_are_valid(confidence):
    assert ComplaintDetectionResult("Cost", confidence, "evidence").confidence == confidence


@pytest.mark.parametrize("category", ["Banana", "cost", ""])
def test_invalid_category_is_rejected(category):
    with pytest.raises(ValueError, match="Unsupported complaint category"):
        ComplaintDetectionResult(category, 0.5, "evidence")


@pytest.mark.parametrize("confidence", [-0.1, 1.1, True, "0.5"])
def test_invalid_confidence_is_rejected(confidence):
    with pytest.raises(ValueError, match="confidence"):
        ComplaintDetectionResult("Cost", confidence, "evidence")


@pytest.mark.parametrize("evidence", ["", "   "])
def test_empty_evidence_is_rejected(evidence):
    with pytest.raises(ValueError, match="evidence"):
        ComplaintDetectionResult("Cost", 0.5, evidence)


def test_abstract_provider_cannot_be_instantiated():
    with pytest.raises(TypeError):
        ComplaintDetectionProvider() # type: ignore


def test_provider_can_return_multiple_categories_for_one_conversation():
    provider: ComplaintDetectionProvider = FakeComplaintProvider()

    results = provider.detect(Conversation(call_id="1"))

    assert {r.category for r in results} == {"Cost", "Turnaround Time"}