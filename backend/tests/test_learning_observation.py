import pytest

from app.domain.learning_evidence import LearningComponent
from app.domain.learning_observation import LearningObservation


def create_observation() -> LearningObservation:
    return LearningObservation(
        observation_id="OBS_001",
        call_id="CALL_001",
        component=LearningComponent.COMPLAINT_DETECTION,
        description="AI detected a communication complaint.",
        predicted_value="Communication",
        confidence=0.92,
        created_at=100.0,
    )


def test_learning_observation_can_be_created():
    observation = create_observation()

    assert observation.observation_id == "OBS_001"
    assert observation.call_id == "CALL_001"
    assert observation.component == LearningComponent.COMPLAINT_DETECTION
    assert observation.predicted_value == "Communication"


def test_empty_observation_id_is_rejected():
    with pytest.raises(ValueError, match="observation_id"):
        LearningObservation(
            observation_id="",
            call_id="CALL_001",
            component=LearningComponent.GENERAL,
            description="Test observation.",
            predicted_value="Test",
            confidence=0.8,
            created_at=100.0,
        )


def test_empty_call_id_is_rejected():
    with pytest.raises(ValueError, match="call_id"):
        LearningObservation(
            observation_id="OBS_001",
            call_id="",
            component=LearningComponent.GENERAL,
            description="Test observation.",
            predicted_value="Test",
            confidence=0.8,
            created_at=100.0,
        )


def test_empty_description_is_rejected():
    with pytest.raises(ValueError, match="description"):
        LearningObservation(
            observation_id="OBS_001",
            call_id="CALL_001",
            component=LearningComponent.GENERAL,
            description="",
            predicted_value="Test",
            confidence=0.8,
            created_at=100.0,
        )


def test_empty_predicted_value_is_rejected():
    with pytest.raises(ValueError, match="predicted_value"):
        LearningObservation(
            observation_id="OBS_001",
            call_id="CALL_001",
            component=LearningComponent.GENERAL,
            description="Test observation.",
            predicted_value="",
            confidence=0.8,
            created_at=100.0,
        )


def test_confidence_must_be_between_zero_and_one():
    with pytest.raises(ValueError, match="confidence"):
        LearningObservation(
            observation_id="OBS_001",
            call_id="CALL_001",
            component=LearningComponent.GENERAL,
            description="Test observation.",
            predicted_value="Test",
            confidence=1.5,
            created_at=100.0,
        )


def test_negative_created_at_is_rejected():
    with pytest.raises(ValueError, match="created_at"):
        LearningObservation(
            observation_id="OBS_001",
            call_id="CALL_001",
            component=LearningComponent.GENERAL,
            description="Test observation.",
            predicted_value="Test",
            confidence=0.8,
            created_at=-1.0,
        )


def test_learning_observation_is_immutable():
    observation = create_observation()

    with pytest.raises(AttributeError):
        observation.predicted_value = "Changed" # type: ignore