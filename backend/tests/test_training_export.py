"""Reviewed AI outputs as a training file: what each line holds, which
lines can be used to fine-tune a model, and who may download it."""

import json

import pytest
from fastapi.testclient import TestClient

from app.domain.conversation import Conversation
from app.domain.learning_evidence import LearningComponent
from app.domain.learning_feedback import FeedbackSource, FeedbackType, LearningFeedback
from app.domain.learning_observation import LearningObservation
from app.domain.user import UserRole
from app.domain.utterance import SpeakerRole, Utterance
from app.services.audit_log import AuditFilter
from app.services.training_export import (
    ReviewedOutput,
    export_training_data,
    training_example,
)
from tests.test_learning_api import (  # the learning loop's API fixtures
    BASE,
    _call_with_utterance,
    _client_for,
    _correct,
    _observation,
    loop,  # noqa: F401  (a fixture)
)


def _call() -> Conversation:
    call = Conversation("call-1")
    call.add_utterance(Utterance("u1", "How can I help?", SpeakerRole.ICR, ("en",), 0.0, 1.0))
    call.add_utterance(
        Utterance("u2", "Nobody told me the car would be late.", SpeakerRole.CUSTOMER, ("en",), 1.0, 3.0)
    )
    return call


def _observed(component: LearningComponent, predicted: str, observation_id: str = "o1"):
    return LearningObservation(
        observation_id, "call-1", component, "The customer's complaint.", predicted, 0.8, 100.0
    )


def _judged(observation, feedback_type, at: float = 200.0, **values) -> ReviewedOutput:
    feedback = LearningFeedback(
        feedback_id=f"f-{observation.observation_id}",
        observation_id=observation.observation_id,
        feedback_type=feedback_type,
        corrected_value=values.get("corrected"),
        outcome=values.get("outcome"),
        created_at=at,
        call_id="call-1",
        original_value=observation.predicted_value,
        source=values.get("source", FeedbackSource.SUPERVISOR),
        notes=values.get("notes"),
    )
    return ReviewedOutput(observation, feedback)


def test_a_correction_becomes_an_example_with_the_right_answer():
    reviewed = _judged(
        _observed(LearningComponent.COMPLAINT_DETECTION, "Turnaround Time"),
        FeedbackType.HUMAN_CORRECTION,
        corrected="Communication",
        notes="It was about not being told.",
    )

    example = training_example(reviewed, _call())

    assert example["task"] == "complaint_detection"
    assert example["call_id"] == "call-1"
    assert example["transcript"] == (
        "[1] ICR: How can I help?\n[2] CUSTOMER: Nobody told me the car would be late."
    )
    assert (example["ai_output"], example["ai_confidence"]) == ("Turnaround Time", 0.8)
    assert (example["verdict"], example["correct_output"]) == ("corrected", "Communication")
    assert (example["judged_by"], example["judged_at"]) == ("supervisor", 200.0)
    assert example["notes"] == "It was about not being told."
    system, user, assistant = example["messages"]
    assert (system["role"], user["role"], assistant["role"]) == ("system", "user", "assistant")
    assert "complaint category" in system["content"]
    assert "Nobody told me the car would be late." in user["content"]
    assert "About: The customer's complaint." in user["content"]
    assert assistant["content"] == "Communication"


def test_a_question_found_helpful_is_an_example_of_what_to_say():
    reviewed = _judged(
        _observed(LearningComponent.NEXT_QUESTION, "When were you told it would be ready?"),
        FeedbackType.QUESTION_EFFECTIVENESS,
        outcome="helpful",
    )

    example = training_example(reviewed, _call())

    assert example["verdict"] == "confirmed"
    assert example["correct_output"] == "When were you told it would be ready?"
    assert example["messages"][-1]["content"] == "When were you told it would be ready?"


def test_a_question_found_unhelpful_is_kept_without_an_answer_to_learn():
    reviewed = _judged(
        _observed(LearningComponent.NEXT_QUESTION, "What colour is the car?"),
        FeedbackType.QUESTION_EFFECTIVENESS,
        outcome="not_helpful",
    )

    example = training_example(reviewed, _call())

    assert (example["verdict"], example["correct_output"]) == ("rejected", None)
    assert example["ai_output"] == "What colour is the car?"
    assert "messages" not in example


def test_an_example_whose_call_is_gone_is_kept_without_its_transcript():
    reviewed = _judged(
        _observed(LearningComponent.SENTIMENT_ANALYSIS, "NEUTRAL"),
        FeedbackType.HUMAN_CORRECTION,
        corrected="FRUSTRATED",
    )

    example = training_example(reviewed, None)

    assert (example["transcript"], example["correct_output"]) == (None, "FRUSTRATED")
    assert "messages" not in example


def test_the_file_is_one_json_object_per_line_oldest_first_with_counts():
    complaint = _judged(
        _observed(LearningComponent.COMPLAINT_DETECTION, "Cost", "o1"),
        FeedbackType.HUMAN_CORRECTION, at=300.0, corrected="Hygiene",
    )
    tone = _judged(
        _observed(LearningComponent.SENTIMENT_ANALYSIS, "NEUTRAL", "o2"),
        FeedbackType.HUMAN_CORRECTION, at=100.0, corrected="NEGATIVE",
    )
    question = _judged(
        _observed(LearningComponent.NEXT_QUESTION, "மேலும் சொல்லுங்கள்?", "o3"),
        FeedbackType.QUESTION_EFFECTIVENESS, at=200.0, outcome="not_helpful",
    )
    fetched: list[str] = []

    def get_call(call_id: str):
        fetched.append(call_id)
        return _call()

    export = export_training_data([complaint, tone, question], get_call)

    lines = export.content.decode("utf-8").splitlines()
    assert [json.loads(line)["task"] for line in lines] == [
        "sentiment_analysis", "next_question", "complaint_detection",
    ]
    assert (export.examples, export.with_messages) == (3, 2)
    assert export.by_task == {
        "sentiment_analysis": 1, "next_question": 1, "complaint_detection": 1,
    }
    # Other scripts are written as they are, not as escape codes.
    assert "மேலும் சொல்லுங்கள்?" in export.content.decode("utf-8")
    assert export.content.endswith(b"\n")
    assert fetched == ["call-1"]  # a call is read once, however many examples it has


def test_nothing_reviewed_gives_an_empty_file():
    export = export_training_data([], lambda call_id: None)

    assert (export.content, export.examples, export.with_messages, export.by_task) == (b"", 0, 0, {})


# ---- Through the application ----


@pytest.fixture
def admin(loop) -> TestClient:  # noqa: F811
    return _client_for(loop.icr.app, UserRole.ADMIN)


def test_an_admin_sees_how_much_there_is_and_downloads_it(loop, admin):  # noqa: F811
    _call_with_utterance(loop.icr, "call-a")
    _call_with_utterance(loop.icr, "call-b")
    assert _correct(loop.icr, "call-a").status_code == 201
    question = _observation(loop.icr, "call-b", "next_question")
    judged = loop.icr.post(
        f"{BASE}/calls/call-b/feedback",
        json={
            "observation_id": question["observation_id"],
            "feedback_type": "question_effectiveness",
            "outcome": "not_helpful",
        },
    )
    assert judged.status_code == 201

    summary = admin.get(f"{BASE}/training-data").json()
    download = admin.get(f"{BASE}/training-data/export")

    assert summary == {
        "examples": 2,
        "with_messages": 1,
        "by_task": {"complaint_detection": 1, "next_question": 1},
    }
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/x-ndjson")
    assert download.headers["content-disposition"] == 'attachment; filename="training-data.jsonl"'
    assert download.headers["cache-control"] == "no-store"
    correction, rejected = (json.loads(line) for line in download.text.splitlines())
    assert (correction["call_id"], correction["ai_output"], correction["correct_output"]) == (
        "call-a", "Turnaround Time", "Communication",
    )
    assert "[1] CUSTOMER: Nobody told me the car would be late." in correction["transcript"]
    assert correction["judged_by"] == "icr"
    assert (rejected["call_id"], rejected["verdict"]) == ("call-b", "rejected")


def test_an_output_nobody_judged_is_not_in_the_file(loop, admin):  # noqa: F811
    _call_with_utterance(loop.icr, "call-a")

    assert admin.get(f"{BASE}/training-data").json()["examples"] == 0
    assert admin.get(f"{BASE}/training-data/export").text == ""


def test_only_admins_reach_the_training_data_and_a_download_is_on_record(loop, admin):  # noqa: F811
    for client in (loop.icr, loop.supervisor):
        assert client.get(f"{BASE}/training-data").status_code == 403
        assert client.get(f"{BASE}/training-data/export").status_code == 403

    admin.get(f"{BASE}/training-data")  # looking at the count is not a download
    admin.get(f"{BASE}/training-data/export")
    audit_log = admin.app.state.services.audit_log
    audit_log.flush()

    downloads = audit_log.search(AuditFilter(action="export_training_file")).entries
    # Newest first: the admin's download, then the two refusals.
    assert [(e.user_id, e.status_code) for e in downloads] == [
        ("user-ADMIN", 200), ("user-SUPERVISOR", 403), ("user-ICR", 403),
    ]
    assert audit_log.search(AuditFilter(action="training_data")).total == 0
