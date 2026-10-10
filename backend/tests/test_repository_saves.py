"""Saving a record that already exists updates it in place. It used to be
deleted and inserted again, which took the rows referencing it along
(ON DELETE CASCADE) and, for a call, rewrote the whole transcript on every
utterance."""

import pytest
from sqlalchemy import event

from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.learning_evidence import LearningComponent
from app.domain.learning_feedback import FeedbackType, LearningFeedback
from app.domain.learning_observation import LearningObservation
from app.domain.utterance import SpeakerRole, Utterance
from app.infrastructure.database.repositories.conversation_coverage_repository import (
    PostgresConversationCoverageRepository,
)
from app.infrastructure.database.repositories.conversation_repository import (
    PostgresConversationRepository,
)
from app.infrastructure.database.repositories.learning_feedback_repository import (
    PostgresLearningFeedbackRepository,
)
from app.infrastructure.database.repositories.learning_observation_repository import (
    PostgresLearningObservationRepository,
)
from sqlalchemy.exc import IntegrityError

from tests.test_postgresql_persistence import engine, session_factory  # noqa: F401  (fixtures)


def _utterance(index: int, transcript: str | None = None, call: str = "call-1") -> Utterance:
    return Utterance(
        utterance_id=f"{call}-u{index}",
        transcript=transcript or f"line {index}",
        speaker_role=SpeakerRole.CUSTOMER,
        languages=("en",),
        start_time=float(index),
        end_time=float(index) + 1.0,
    )


@pytest.fixture
def statements(engine):  # noqa: F811
    """The SQL statements executed, as "VERB table" (e.g. "INSERT utterances")."""
    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        words = statement.split()
        verb = words[0].upper()
        if verb in ("INSERT", "DELETE"):
            seen.append(f"{verb} {words[2]}")
        elif verb == "UPDATE":
            seen.append(f"{verb} {words[1]}")

    event.listen(engine, "before_cursor_execute", record)
    yield seen
    event.remove(engine, "before_cursor_execute", record)


# ---- A call and its utterances ----

def test_saving_a_call_again_writes_only_the_new_utterance(session_factory, statements):  # noqa: F811
    repo = PostgresConversationRepository(session_factory)
    conversation = Conversation(call_id="call-1", start_time=0.0)
    for index in range(50):
        conversation.add_utterance(_utterance(index))
    repo.save(conversation)
    statements.clear()

    conversation.add_utterance(_utterance(50))
    repo.save(conversation)

    # One new row; the fifty stored ones and the call itself are untouched.
    assert statements == ["INSERT utterances"]
    assert repo.get("call-1").utterance_count == 51


def test_a_growing_last_utterance_is_updated_in_place(session_factory, statements):  # noqa: F811
    repo = PostgresConversationRepository(session_factory)
    conversation = Conversation(call_id="call-1", start_time=0.0)
    conversation.add_utterance(_utterance(0))
    conversation.add_utterance(_utterance(1, "The brakes"))
    repo.save(conversation)
    statements.clear()

    conversation.replace_latest_utterance(_utterance(1, "The brakes make a noise"))
    repo.save(conversation)

    assert statements == ["UPDATE utterances"]
    assert [u.transcript for u in repo.get("call-1").utterances] == [
        "line 0",
        "The brakes make a noise",
    ]


def test_a_revised_transcript_drops_the_utterances_it_no_longer_has(session_factory):  # noqa: F811
    repo = PostgresConversationRepository(session_factory)
    conversation = Conversation(call_id="call-1", start_time=0.0)
    for index in range(3):
        conversation.add_utterance(_utterance(index))
    repo.save(conversation)

    conversation.replace_transcript((_utterance(1, "kept, reworded"), _utterance(7, "new")))
    repo.save(conversation)

    loaded = repo.get("call-1")
    assert [(u.utterance_id, u.transcript) for u in loaded.utterances] == [
        ("call-1-u1", "kept, reworded"),
        ("call-1-u7", "new"),
    ]


def test_completing_a_call_updates_its_row(session_factory, statements):  # noqa: F811
    repo = PostgresConversationRepository(session_factory)
    conversation = Conversation(call_id="call-1", start_time=0.0)
    conversation.add_utterance(_utterance(0))
    repo.save(conversation)
    statements.clear()

    conversation.complete(end_time=30.0)
    repo.save(conversation)

    assert statements == ["UPDATE conversations"]
    loaded = repo.get("call-1")
    assert (loaded.status.value, loaded.end_time, loaded.utterance_count) == ("completed", 30.0, 1)


def test_an_utterance_id_used_by_another_call_is_still_refused(session_factory):  # noqa: F811
    repo = PostgresConversationRepository(session_factory)
    first = Conversation(call_id="call-1", start_time=0.0)
    first.add_utterance(_utterance(0))
    repo.save(first)
    second = Conversation(call_id="call-2", start_time=0.0)
    repo.save(second)

    second.add_utterance(_utterance(0))  # the same utterance_id as call-1's
    with pytest.raises(IntegrityError):
        repo.save(second)

    # Neither taken from the first call nor added to the second.
    assert repo.get("call-1").utterance_count == 1
    assert repo.get("call-2").utterance_count == 0


# ---- A call's complaint coverage ----

def test_coverage_saved_again_updates_adds_and_removes_complaints(session_factory, statements):  # noqa: F811
    repo = PostgresConversationCoverageRepository(session_factory)
    coverage = ConversationCoverage(call_id="call-1")
    coverage.get_or_add("Cost").detect()
    coverage.get_or_add("Service Quality").detect()
    repo.save(coverage)
    statements.clear()

    changed = ConversationCoverage(call_id="call-1")
    changed.get_or_add("Cost").status = ComplaintCoverageStatus.PROBED
    changed.get_or_add("Communication").detect()
    repo.save(changed)

    assert sorted(statements) == [
        "DELETE complaint_coverages",
        "INSERT complaint_coverages",
        "UPDATE complaint_coverages",
    ]
    loaded = repo.get("call-1")
    assert {c.category: c.status for c in loaded.complaints} == {
        "Cost": ComplaintCoverageStatus.PROBED,
        "Communication": ComplaintCoverageStatus.DETECTED,
    }


def test_unchanged_coverage_writes_nothing(session_factory, statements):  # noqa: F811
    repo = PostgresConversationCoverageRepository(session_factory)
    coverage = ConversationCoverage(call_id="call-1")
    coverage.get_or_add("Cost").detect()
    repo.save(coverage)
    statements.clear()

    repo.save(coverage)

    assert statements == []


# ---- A row other rows refer to ----

def test_saving_an_observation_again_keeps_its_feedback(session_factory):  # noqa: F811
    observations = PostgresLearningObservationRepository(session_factory)
    feedback = PostgresLearningFeedbackRepository(session_factory)
    observation = LearningObservation(
        observation_id="obs-1",
        call_id="call-1",
        component=LearningComponent.COMPLAINT_DETECTION,
        description="AI output for complaint_detection.",
        predicted_value="Cost",
        confidence=0.6,
        created_at=1.0,
    )
    observations.save(observation)
    feedback.save(
        LearningFeedback(
            feedback_id="fb-1",
            observation_id="obs-1",
            feedback_type=FeedbackType.HUMAN_CORRECTION,
            corrected_value="No complaint",
            outcome=None,
            created_at=2.0,
            call_id="call-1",
        )
    )

    # Feedback refers to its observation with ON DELETE CASCADE: deleting
    # and re-inserting the observation removed the feedback.
    observations.save(observation)

    assert [f.feedback_id for f in feedback.get_by_observation_id("obs-1")] == ["fb-1"]
