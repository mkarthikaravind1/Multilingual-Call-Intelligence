"""Tests for the LearningPattern domain model."""

import pytest

from app.domain.learning_evidence import LearningComponent
from app.domain.learning_pattern import LearningPattern

# Picks an arbitrary real member of the existing enum so these tests don't
# depend on which specific components LearningComponent defines.
VALID_COMPONENT = next(iter(LearningComponent))


def _make_kwargs(**overrides):
    kwargs = {
        "pattern_id": "pattern-1",
        "component": VALID_COMPONENT,
        "description": "Repeated misclassification of refund intents",
        "occurrence_count": 3,
        "evidence_ids": ["evidence-1", "evidence-2"],
        "suggested_improvement": "Add more refund-intent training examples",
        "created_at": 1_700_000_000.0,
    }
    kwargs.update(overrides)
    return kwargs


def test_create_valid_learning_pattern():
    pattern = LearningPattern(**_make_kwargs())

    assert pattern.pattern_id == "pattern-1"
    assert pattern.component == VALID_COMPONENT
    assert pattern.description == "Repeated misclassification of refund intents"
    assert pattern.occurrence_count == 3
    assert pattern.evidence_ids == ["evidence-1", "evidence-2"]
    assert pattern.suggested_improvement == "Add more refund-intent training examples"
    assert pattern.created_at == 1_700_000_000.0


@pytest.mark.parametrize("bad_pattern_id", ["", "   ", None, 123])
def test_invalid_pattern_id_raises(bad_pattern_id):
    with pytest.raises(ValueError):
        LearningPattern(**_make_kwargs(pattern_id=bad_pattern_id))


@pytest.mark.parametrize("bad_component", ["nlu", 1, None, object()])
def test_invalid_component_raises(bad_component):
    with pytest.raises(ValueError):
        LearningPattern(**_make_kwargs(component=bad_component))


@pytest.mark.parametrize("bad_description", ["", "   ", None, 42])
def test_invalid_description_raises(bad_description):
    with pytest.raises(ValueError):
        LearningPattern(**_make_kwargs(description=bad_description))


@pytest.mark.parametrize("bad_count", [0, -1, 1.5, "3", None])
def test_invalid_occurrence_count_raises(bad_count):
    with pytest.raises(ValueError):
        LearningPattern(**_make_kwargs(occurrence_count=bad_count))


@pytest.mark.parametrize(
    "bad_evidence_ids",
    [
        [],
        None,
        "evidence-1",
        ["evidence-1", ""],
        ["evidence-1", None],
        [123],
    ],
)
def test_invalid_evidence_ids_raises(bad_evidence_ids):
    with pytest.raises(ValueError):
        LearningPattern(**_make_kwargs(evidence_ids=bad_evidence_ids))


@pytest.mark.parametrize("bad_improvement", ["", "   ", None, 7])
def test_invalid_suggested_improvement_raises(bad_improvement):
    with pytest.raises(ValueError):
        LearningPattern(**_make_kwargs(suggested_improvement=bad_improvement))


@pytest.mark.parametrize("bad_created_at", [-1, -0.001, "now", None])
def test_invalid_created_at_raises(bad_created_at):
    with pytest.raises(ValueError):
        LearningPattern(**_make_kwargs(created_at=bad_created_at))


def test_learning_pattern_is_frozen():
    pattern = LearningPattern(**_make_kwargs())

    with pytest.raises(Exception):
        pattern.pattern_id = "changed" # type: ignore