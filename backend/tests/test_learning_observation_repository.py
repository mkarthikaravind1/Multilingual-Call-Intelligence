from app.domain.learning_evidence import LearningComponent
from app.domain.learning_observation import LearningObservation
from app.domain.learning_observation_repository import (
    InMemoryLearningObservationRepository,
)


def make_observation(observation_id: str, call_id: str = "CALL_001") -> LearningObservation:
    return LearningObservation(
        observation_id=observation_id,
        call_id=call_id,
        component=LearningComponent.COMPLAINT_DETECTION,
        description="AI detected a complaint.",
        predicted_value="Turnaround Time",
        confidence=0.9,
        created_at=100.0,
    )


def test_saves_and_gets_by_id():
    repository = InMemoryLearningObservationRepository()
    observation = make_observation("OBS_001")

    repository.save(observation)

    assert repository.get("OBS_001") == observation


def test_missing_observation_returns_none():
    assert InMemoryLearningObservationRepository().get("UNKNOWN") is None


def test_gets_by_call_id():
    repository = InMemoryLearningObservationRepository()
    first = make_observation("OBS_001", "CALL_001")
    second = make_observation("OBS_002", "CALL_001")
    other = make_observation("OBS_003", "CALL_002")
    for observation in (first, second, other):
        repository.save(observation)

    assert repository.get_by_call_id("CALL_001") == (first, second)


def test_unknown_call_id_returns_empty_tuple():
    assert InMemoryLearningObservationRepository().get_by_call_id("CALL_404") == ()


def test_list_all_returns_everything():
    repository = InMemoryLearningObservationRepository()
    first = make_observation("OBS_001")
    second = make_observation("OBS_002", "CALL_002")
    repository.save(first)
    repository.save(second)

    assert repository.list_all() == (first, second)


def test_list_all_empty():
    assert InMemoryLearningObservationRepository().list_all() == ()


def test_saving_same_id_replaces_existing():
    repository = InMemoryLearningObservationRepository()
    repository.save(make_observation("OBS_001"))
    replacement = make_observation("OBS_001")

    repository.save(replacement)

    assert repository.list_all() == (replacement,)