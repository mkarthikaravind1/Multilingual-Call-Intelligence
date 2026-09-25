from typing import Any
import pytest
from app.domain.learning_feedback import FeedbackType, LearningFeedback
from app.domain.learning_feedback import FeedbackSource, FeedbackType, LearningFeedback

def create_feedback() -> LearningFeedback:
    return LearningFeedback(
        feedback_id="FEEDBACK_001",
        observation_id="OBS_001",
        feedback_type=FeedbackType.HUMAN_CORRECTION,
        corrected_value="Communication",
        outcome=None,
        created_at=200.0,
    )


def test_learning_feedback_can_be_created():
    feedback = create_feedback()

    assert feedback.feedback_id == "FEEDBACK_001"
    assert feedback.observation_id == "OBS_001"
    assert feedback.feedback_type == FeedbackType.HUMAN_CORRECTION
    assert feedback.corrected_value == "Communication"


def test_feedback_can_contain_outcome_without_correction():
    feedback = LearningFeedback(
        feedback_id="FEEDBACK_002",
        observation_id="OBS_001",
        feedback_type=FeedbackType.OUTCOME,
        corrected_value=None,
        outcome="Customer accepted the estimate.",
        created_at=200.0,
    )

    assert feedback.corrected_value is None
    assert feedback.outcome == "Customer accepted the estimate."


def test_empty_feedback_id_is_rejected():
    with pytest.raises(ValueError, match="feedback_id"):
        LearningFeedback(
            feedback_id="",
            observation_id="OBS_001",
            feedback_type=FeedbackType.OUTCOME,
            corrected_value=None,
            outcome="Accepted",
            created_at=200.0,
        )


def test_empty_observation_id_is_rejected():
    with pytest.raises(ValueError, match="observation_id"):
        LearningFeedback(
            feedback_id="FEEDBACK_001",
            observation_id="",
            feedback_type=FeedbackType.OUTCOME,
            corrected_value=None,
            outcome="Accepted",
            created_at=200.0,
        )


def test_blank_correction_is_rejected():
    with pytest.raises(ValueError, match="corrected_value"):
        LearningFeedback(
            feedback_id="FEEDBACK_001",
            observation_id="OBS_001",
            feedback_type=FeedbackType.HUMAN_CORRECTION,
            corrected_value="",
            outcome=None,
            created_at=200.0,
        )


def test_blank_outcome_is_rejected():
    with pytest.raises(ValueError, match="outcome"):
        LearningFeedback(
            feedback_id="FEEDBACK_001",
            observation_id="OBS_001",
            feedback_type=FeedbackType.OUTCOME,
            corrected_value=None,
            outcome="",
            created_at=200.0,
        )


def test_feedback_requires_correction_or_outcome():
    with pytest.raises(
        ValueError,
        match="corrected_value or outcome",
    ):
        LearningFeedback(
            feedback_id="FEEDBACK_001",
            observation_id="OBS_001",
            feedback_type=FeedbackType.OUTCOME,
            corrected_value=None,
            outcome=None,
            created_at=200.0,
        )


def test_negative_created_at_is_rejected():
    with pytest.raises(ValueError, match="created_at"):
        LearningFeedback(
            feedback_id="FEEDBACK_001",
            observation_id="OBS_001",
            feedback_type=FeedbackType.OUTCOME,
            corrected_value=None,
            outcome="Accepted",
            created_at=-1.0,
        )


def test_learning_feedback_is_immutable():
    feedback = create_feedback()

    with pytest.raises(AttributeError):
        feedback.outcome = "Changed" # type: ignore

def test_new_fields_have_backward_compatible_defaults():
    feedback = create_feedback()

    assert feedback.call_id is None
    assert feedback.original_value is None
    assert feedback.source is FeedbackSource.ICR
    assert feedback.notes is None


def test_new_fields_are_stored():
    feedback = LearningFeedback(
        feedback_id="FEEDBACK_003",
        observation_id="OBS_001",
        feedback_type=FeedbackType.HUMAN_CORRECTION,
        corrected_value="Communication",
        outcome=None,
        created_at=200.0,
        call_id="CALL_001",
        original_value="Turnaround Time",
        source=FeedbackSource.SUPERVISOR,
        notes="Customer was not informed.",
    )

    assert feedback.call_id == "CALL_001"
    assert feedback.original_value == "Turnaround Time"
    assert feedback.source is FeedbackSource.SUPERVISOR
    assert feedback.notes == "Customer was not informed."


def test_blank_call_id_is_rejected():
    with pytest.raises(ValueError, match="call_id"):
        LearningFeedback(
            feedback_id="FEEDBACK_001",
            observation_id="OBS_001",
            feedback_type=FeedbackType.OUTCOME,
            corrected_value=None,
            outcome="Accepted",
            created_at=200.0,
            call_id="  ",
        )


def test_invalid_source_is_rejected():
    with pytest.raises(ValueError, match="source"):
        LearningFeedback(
            feedback_id="FEEDBACK_001",
            observation_id="OBS_001",
            feedback_type=FeedbackType.OUTCOME,
            corrected_value=None,
            outcome="Accepted",
            created_at=200.0,
            source="icr",  # type: ignore
        )

@pytest.mark.parametrize("field", ["original_value", "notes"])
def test_blank_optional_text_fields_are_rejected(field):
    kwargs: dict[str, Any] = {
        "feedback_id": "FEEDBACK_001",
        "observation_id": "OBS_001",
        "feedback_type": FeedbackType.OUTCOME,
        "corrected_value": None,
        "outcome": "Accepted",
        "created_at": 200.0,
        field: " ",
    }

    with pytest.raises(ValueError, match=field):
        LearningFeedback(**kwargs)