from app.domain.learning_feedback import FeedbackType, LearningFeedback
from app.domain.learning_feedback_repository import InMemoryLearningFeedbackRepository


def make_feedback(
    feedback_id: str, observation_id: str = "OBS_001", call_id: str | None = "CALL_001"
) -> LearningFeedback:
    return LearningFeedback(
        feedback_id=feedback_id,
        observation_id=observation_id,
        feedback_type=FeedbackType.HUMAN_CORRECTION,
        corrected_value="Communication",
        outcome=None,
        created_at=200.0,
        call_id=call_id,
    )


def test_saves_and_gets_by_id():
    repository = InMemoryLearningFeedbackRepository()
    feedback = make_feedback("FB_001")

    repository.save(feedback)

    assert repository.get("FB_001") == feedback


def test_missing_feedback_returns_none():
    assert InMemoryLearningFeedbackRepository().get("UNKNOWN") is None


def test_gets_by_observation_id():
    repository = InMemoryLearningFeedbackRepository()
    first = make_feedback("FB_001", "OBS_001")
    second = make_feedback("FB_002", "OBS_001")
    other = make_feedback("FB_003", "OBS_002")
    for feedback in (first, second, other):
        repository.save(feedback)

    assert repository.get_by_observation_id("OBS_001") == (first, second)
    assert repository.get_by_observation_id("OBS_404") == ()


def test_gets_by_call_id():
    repository = InMemoryLearningFeedbackRepository()
    first = make_feedback("FB_001", call_id="CALL_001")
    other = make_feedback("FB_002", call_id="CALL_002")
    repository.save(first)
    repository.save(other)

    assert repository.get_by_call_id("CALL_001") == (first,)
    assert repository.get_by_call_id("CALL_404") == ()


def test_list_all():
    repository = InMemoryLearningFeedbackRepository()
    assert repository.list_all() == ()
    first = make_feedback("FB_001")
    second = make_feedback("FB_002")
    repository.save(first)
    repository.save(second)

    assert repository.list_all() == (first, second)


def test_saving_same_id_replaces_existing():
    repository = InMemoryLearningFeedbackRepository()
    repository.save(make_feedback("FB_001"))
    replacement = make_feedback("FB_001")

    repository.save(replacement)

    assert repository.list_all() == (replacement,)