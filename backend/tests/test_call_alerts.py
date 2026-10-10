"""On-screen alerts on live calls (each rule, raised once, cleared when no
longer true), the stored complaint confidence, what executives do with
suggested questions, and the supervisor's live view."""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.ai.complaint.provider import ComplaintDetectionProvider, ComplaintDetectionResult
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentLabel, SentimentResult
from app.api.app_factory import create_app
from app.api.v1.telephony_ws import _note_audio
from app.api.wiring import build_api_services
from app.core.config import Settings
from app.domain.call_alert import (
    CallAlert,
    CallAlertType,
    QuestionOutcome,
    QuestionOutcomeChoice,
)
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.user import User, UserRole
from app.domain.utterance import SpeakerRole, Utterance
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import build_session_factory
from app.infrastructure.database.repositories.call_alert_repository import (
    PostgresCallAlertRepository,
    PostgresQuestionOutcomeRepository,
)
from app.infrastructure.database.repositories.conversation_coverage_repository import (
    PostgresConversationCoverageRepository,
)
from app.security.jwt import create_access_token
from app.services.call_alerts import (
    AlertRules,
    CallAlertService,
    InMemoryCallAlertRepository,
    InMemoryQuestionOutcomeRepository,
    count_outcomes,
)
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.telephony_audio_buffer import BufferedAudioChunk

UNCOVERED = CallAlertType.UNCOVERED_CATEGORY
SEVERE = CallAlertType.HIGH_SEVERITY_CATEGORY
UNSURE = CallAlertType.LOW_CONFIDENCE
AUDIO = CallAlertType.POOR_AUDIO


class _Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _service(clock: _Clock | None = None, **rules) -> CallAlertService:
    return CallAlertService(
        InMemoryCallAlertRepository(), rules=AlertRules(**rules), clock=clock or _Clock()
    )


def _call(*confidences: float | None) -> Conversation:
    call = Conversation(call_id="call-1")
    for index, confidence in enumerate(confidences):
        call.add_utterance(
            Utterance(f"u{index}", "Hello.", SpeakerRole.CUSTOMER, ("en",), float(index), index + 0.5, confidence)
        )
    return call


def _coverage(**complaints) -> ConversationCoverage:
    """Complaints as category=(status, confidence, detected_at)."""
    coverage = ConversationCoverage(call_id="call-1")
    for category, (status, confidence, detected_at) in complaints.items():
        complaint = coverage.add(category.replace("_", " "))
        complaint.status = ComplaintCoverageStatus(status)
        complaint.confidence = confidence
        complaint.detected_at = detected_at
    return coverage


def _standing(alerts) -> set:
    return {(a.alert_type, a.subject) for a in alerts if a.is_open}


# ---- The rules ----

def test_a_complaint_not_asked_about_alerts_after_a_minute_and_clears_once_asked():
    clock = _Clock(1_000.0)
    service = _service(clock)
    call = _call()

    assert service.refresh(call, _coverage(Cost=("detected", 0.9, 1_000.0))) == ()
    clock.now = 1_059.0
    assert service.refresh(call, _coverage(Cost=("detected", 0.9, 1_000.0))) == ()

    clock.now = 1_060.0
    alerts = service.refresh(call, _coverage(Cost=("detected", 0.9, 1_000.0)))
    assert _standing(alerts) == {(UNCOVERED, "Cost")}
    assert alerts[0].message == "The Cost complaint has not been asked about yet."
    assert alerts[0].raised_at == 1_060.0

    clock.now = 1_090.0
    cleared = service.refresh(call, _coverage(Cost=("probed", 0.9, 1_000.0)))
    assert _standing(cleared) == set()
    assert (cleared[0].raised_at, cleared[0].cleared_at) == (1_060.0, 1_090.0)


def test_an_alert_is_raised_once_however_often_it_is_checked():
    clock = _Clock(2_000.0)
    service = _service(clock)
    coverage = _coverage(Cost=("detected", 0.9, 1_000.0))

    first = service.refresh(_call(), coverage)
    clock.now = 2_500.0
    again = service.refresh(_call(), coverage)

    assert len(again) == 1
    assert again[0] == first[0]
    assert service.list_for_call("call-1") == again


def test_an_alert_that_comes_back_is_raised_again():
    clock = _Clock(1_000.0)
    service = _service(clock)
    unsure = _coverage(Cost=("probed", 0.4, 1_000.0))

    service.refresh(_call(), unsure)
    clock.now = 1_100.0
    service.refresh(_call(), _coverage(Cost=("probed", 0.8, 1_000.0)))
    clock.now = 1_200.0
    back = service.refresh(_call(), unsure)

    assert _standing(back) == {(UNSURE, "Cost")}
    assert (back[0].raised_at, back[0].cleared_at) == (1_200.0, None)


def test_severe_categories_alert_as_soon_as_they_are_detected():
    service = _service()

    alerts = service.refresh(
        _call(),
        _coverage(
            Hygiene=("detected", 0.9, 1_000.0),
            Brake_Safety=("probed", 0.9, 1_000.0),
            Cost=("detected", 0.9, 1_000.0),
            Communication=("not_raised", None, None),
        ),
    )

    assert _standing(alerts) == {(SEVERE, "Hygiene"), (SEVERE, "Brake Safety")}
    assert "Hygiene is a high-severity complaint." in {a.message for a in alerts}


def test_a_complaint_detected_with_low_confidence_alerts():
    alerts = _service().refresh(
        _call(),
        _coverage(
            Cost=("probed", 0.59, 1_000.0),
            TAT=("probed", 0.6, 1_000.0),
            Other=("probed", None, 1_000.0),
        ),
    )

    assert _standing(alerts) == {(UNSURE, "Cost")}
    assert alerts[0].message == "The Cost complaint was detected with low confidence (59%)."


def test_speech_nothing_could_be_made_of_is_poor_audio():
    service = _service()
    call = _call()

    for recognised in (True, False, True, False):
        service.note_audio("call-1", recognised)
    assert service.refresh(call, None) == ()

    service.note_audio("call-1", False)
    alerts = service.refresh(call, None)
    assert _standing(alerts) == {(AUDIO, "")}
    assert "3 of the last 6" in alerts[0].message

    # Six good stretches push the bad ones out of what is remembered.
    for _ in range(6):
        service.note_audio("call-1", True)
    assert _standing(service.refresh(call, None)) == set()


def test_low_transcription_confidence_is_poor_audio_when_the_recogniser_gives_one():
    service = _service()

    assert service.refresh(_call(None, None, None, None), None) == ()
    assert service.refresh(_call(0.9, 0.8, 0.7), None) == ()
    assert service.refresh(_call(0.3, 0.2), None) == ()  # too few lines to judge
    alerts = service.refresh(_call(0.9, 0.9, 0.9, 0.5, 0.5, 0.6, 0.5, 0.4), None)

    assert _standing(alerts) == {(AUDIO, "")}
    assert "low confidence (50%)" in alerts[0].message


def test_one_calls_audio_and_alerts_do_not_touch_anothers():
    service = _service()
    for _ in range(3):
        service.note_audio("call-2", False)

    assert service.refresh(_call(), None) == ()
    assert service.list_for_calls(["call-1", "call-2", "call-3"]) == {}


def test_silence_that_transcribes_to_nothing_is_not_counted_as_poor_audio():
    service = _service()
    silent = BufferedAudioChunk(audio=b"\x00\x00", start_time=0.0, end_time=1.0, has_speech=False)
    spoken = BufferedAudioChunk(audio=b"\x00\x00", start_time=0.0, end_time=1.0, has_speech=True)

    for _ in range(5):
        _note_audio(service, "call-1", silent, recognised=False)
    assert service.refresh(_call(), None) == ()

    for _ in range(3):
        _note_audio(service, "call-1", spoken, recognised=False)
    _note_audio(None, "call-1", spoken, recognised=False)  # alerts not set up: nothing to do
    assert _standing(service.refresh(_call(), None)) == {(AUDIO, "")}


def test_the_rules_come_from_the_settings():
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        alert_uncovered_after_seconds=20,
        alert_high_severity_categories=" Hygiene , Staff Behaviour ,",
        alert_low_confidence_below=0.5,
        alert_poor_audio_unrecognised_chunks=2,
    )

    rules = AlertRules.from_settings(settings)

    assert rules.uncovered_after_seconds == 20
    assert rules.high_severity_categories == {"hygiene", "staff behaviour"}
    assert (rules.low_confidence_below, rules.unrecognised_chunks) == (0.5, 2)
    defaults = AlertRules.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
    assert defaults == AlertRules()


# ---- Confidence and detection time on the complaint ----

class _Detections(ComplaintDetectionProvider):
    def __init__(self, *rounds) -> None:
        self._rounds = list(rounds)

    def detect(self, conversation, learning_context=()):
        return self._rounds.pop(0)


def test_a_complaint_keeps_its_latest_confidence_and_when_it_was_first_detected():
    clock = _Clock(500.0)
    service = ComplaintAnalysisService(
        _Detections(
            [ComplaintDetectionResult("Cost", 0.55, "Said so.")],
            [ComplaintDetectionResult("Cost", 0.9, "Said so again.", probed=True)],
        ),
        clock=clock,
    )
    call = _call(None)

    coverage = service.analyze(call, ConversationCoverage(call_id="call-1"))
    assert (coverage.get("Cost").confidence, coverage.get("Cost").detected_at) == (0.55, 500.0)

    clock.now = 600.0
    coverage = service.analyze(call, coverage)
    assert (coverage.get("Cost").confidence, coverage.get("Cost").detected_at) == (0.9, 500.0)


# ---- The database ----

@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield build_session_factory(engine)
    engine.dispose()


def test_confidence_alerts_and_outcomes_are_stored(session_factory):
    coverages = PostgresConversationCoverageRepository(session_factory)
    coverages.save(_coverage(Cost=("detected", 0.72, 123.0), Other=("detected", None, None)))
    stored = coverages.get("call-1")
    assert (stored.get("Cost").confidence, stored.get("Cost").detected_at) == (0.72, 123.0)
    assert (stored.get("Other").confidence, stored.get("Other").detected_at) == (None, None)

    alerts = PostgresCallAlertRepository(session_factory)
    alerts.save(CallAlert("call-1", UNCOVERED, "Cost", "Not asked about.", 10.0))
    alerts.save(CallAlert("call-1", AUDIO, "", "Poor audio.", 5.0))
    alerts.save(CallAlert("call-1", UNCOVERED, "Cost", "Not asked about.", 10.0, cleared_at=20.0))
    alerts.save(CallAlert("call-2", SEVERE, "Hygiene", "Severe.", 1.0))
    found = alerts.list_for_calls(["call-1", "call-3"])
    assert [(a.alert_type, a.subject, a.cleared_at) for a in found["call-1"]] == [
        (AUDIO, "", None),
        (UNCOVERED, "Cost", 20.0),
    ]
    assert "call-3" not in found and alerts.list_for_calls([]) == {}

    outcomes = PostgresQuestionOutcomeRepository(session_factory)
    accepted, skipped = QuestionOutcomeChoice.ACCEPTED, QuestionOutcomeChoice.SKIPPED
    outcomes.save(QuestionOutcome("call-1", "When was it due?", "TAT", skipped, "asha", 1.0))
    outcomes.save(QuestionOutcome("call-1", "What was quoted?", "Cost", accepted, "asha", 2.0))
    # Choosing again replaces the earlier choice.
    outcomes.save(QuestionOutcome("call-1", "When was it due?", "TAT", accepted, "asha", 3.0))
    listed = outcomes.list_for_calls(["call-1"])["call-1"]
    assert [(o.question, o.outcome) for o in listed] == [
        ("What was quoted?", accepted),
        ("When was it due?", accepted),
    ]
    assert count_outcomes(listed) == (2, 0)


def test_the_in_memory_outcome_store_behaves_the_same():
    outcomes = InMemoryQuestionOutcomeRepository()
    accepted, skipped = QuestionOutcomeChoice.ACCEPTED, QuestionOutcomeChoice.SKIPPED
    outcomes.save(QuestionOutcome("call-1", "Q1", "TAT", skipped, "asha", 1.0))
    outcomes.save(QuestionOutcome("call-1", "Q2", "Cost", accepted, "asha", 2.0))
    outcomes.save(QuestionOutcome("call-1", "Q1", "TAT", skipped, "asha", 3.0))

    listed = outcomes.list_for_calls(["call-1", "call-2"])

    assert set(listed) == {"call-1"}
    assert count_outcomes(listed["call-1"]) == (1, 1)


# ---- The API ----

class _Complaints(ComplaintDetectionProvider):
    def __init__(self) -> None:
        self.results: list[ComplaintDetectionResult] = []

    def detect(self, conversation, learning_context=()):
        return list(self.results)


class _Negative(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.FRUSTRATED, 0.9, "Said so.")


class _NoQuestions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


def _api():
    complaints = _Complaints()
    services = build_api_services(
        complaints, _Negative(), _NoQuestions(), Settings(_env_file=None)  # type: ignore[call-arg]
    )
    client = TestClient(create_app(services))

    def sign_in(user_id: str, role: UserRole, **fields) -> dict[str, str]:
        user = User(user_id, f"{user_id}@example.com", "hash", role, True, time.time(), **fields)
        services.user_repository.save(user)
        return {"Authorization": f"Bearer {create_access_token(user)}"}

    return client, complaints, sign_in


def _say(client, headers, call_id: str, index: int = 0) -> dict:
    return client.post(
        f"/api/v1/calls/{call_id}/utterances",
        json={
            "utterance_id": f"{call_id}-u{index}",
            "transcript": "The washroom was dirty.",
            "speaker_role": "CUSTOMER",
            "languages": ["en"],
            "start_time": float(index),
            "end_time": index + 0.5,
        },
        headers=headers,
    ).json()


def test_the_analysis_carries_the_confidence_and_the_alerts():
    client, complaints, sign_in = _api()
    icr = sign_in("asha", UserRole.ICR)
    client.post("/api/v1/calls", json={"call_id": "c1", "start_time": None}, headers=icr)
    complaints.results = [ComplaintDetectionResult("Hygiene", 0.45, "Dirty washroom.")]

    said = _say(client, icr, "c1")

    assert said["coverage"]["complaints"] == [
        {"category": "Hygiene", "status": "detected", "confidence": 0.45}
    ]
    assert {(a["alert_type"], a["subject"], a["cleared_at"]) for a in said["alerts"]} == {
        ("high_severity_category", "Hygiene", None),
        ("low_confidence", "Hygiene", None),
    }
    # Reading the call again shows the same alerts, and does not raise them twice.
    read = client.get("/api/v1/calls/c1/analysis", headers=icr).json()
    assert read["alerts"] == said["alerts"]

    # The executive asks about it and the detector is now sure.
    complaints.results = [ComplaintDetectionResult("Hygiene", 0.9, "Dirty washroom.", probed=True)]
    later = _say(client, icr, "c1", 1)
    standing = {a["alert_type"] for a in later["alerts"] if a["cleared_at"] is None}
    assert standing == {"high_severity_category"}
    assert later["coverage"]["complaints"][0]["status"] == "probed"

    # Alerts stay with the call after it ends.
    client.post("/api/v1/calls/c1/complete", json={}, headers=icr)
    after = client.get("/api/v1/calls/c1/analysis", headers=icr).json()
    assert {a["alert_type"] for a in after["alerts"]} == {
        "high_severity_category",
        "low_confidence",
    }


def test_the_live_view_lists_active_calls_for_supervisors_and_admins():
    client, complaints, sign_in = _api()
    asha = sign_in("asha", UserRole.ICR, display_name="Asha")
    supervisor = sign_in("sup", UserRole.SUPERVISOR)
    client.post("/api/v1/calls", json={"call_id": "live", "start_time": None}, headers=asha)
    client.post("/api/v1/calls", json={"call_id": "quiet", "start_time": None}, headers=asha)
    client.post("/api/v1/calls", json={"call_id": "ended", "start_time": None}, headers=asha)
    complaints.results = [ComplaintDetectionResult("Hygiene", 0.9, "Dirty washroom.")]
    _say(client, asha, "live")
    client.post("/api/v1/calls/ended/complete", json={}, headers=asha)

    body = client.get("/api/v1/live-calls", headers=supervisor).json()

    assert body["total"] == 2
    assert abs(body["now"] - time.time()) < 60
    calls = {call["call_id"]: call for call in body["items"]}
    assert set(calls) == {"live", "quiet"}
    live = calls["live"]
    assert (live["executive_name"], live["direction"], live["utterance_count"]) == (
        "Asha",
        "inbound",
        1,
    )
    assert live["sentiment"] == "FRUSTRATED"
    assert live["complaints"] == [
        {"category": "Hygiene", "status": "detected", "confidence": 0.9}
    ]
    assert [a["alert_type"] for a in live["alerts"]] == ["high_severity_category"]
    assert live["escalation_level"] == "watch"
    quiet = calls["quiet"]
    assert (quiet["sentiment"], quiet["complaints"], quiet["alerts"]) == (None, [], [])

    assert client.get("/api/v1/live-calls", headers=sign_in("adm", UserRole.ADMIN)).status_code == 200
    assert client.get("/api/v1/live-calls", headers=asha).status_code == 403
    assert client.get("/api/v1/live-calls").status_code == 401


def test_executives_accept_or_skip_suggested_questions_and_the_scorecard_counts_them():
    client, _, sign_in = _api()
    asha = sign_in("asha", UserRole.ICR, display_name="Asha")
    supervisor = sign_in("sup", UserRole.SUPERVISOR)
    client.post("/api/v1/calls", json={"call_id": "c1", "start_time": None}, headers=asha)
    path = "/api/v1/calls/c1/question-outcomes"

    def choose(question: str, outcome: str):
        return client.post(
            path,
            json={"question": question, "target_category": "Cost", "outcome": outcome},
            headers=asha,
        )

    assert choose("What was quoted?", "accepted").status_code == 200
    assert choose("Who approved it?", "skipped").status_code == 200
    changed = choose("Who approved it?", "accepted")
    assert changed.json()["outcome"] == "accepted"
    choose("Was it in writing?", "skipped")

    listed = client.get(path, headers=asha).json()
    assert [(o["question"], o["outcome"]) for o in listed] == [
        ("What was quoted?", "accepted"),
        ("Who approved it?", "accepted"),
        ("Was it in writing?", "skipped"),
    ]

    figures = client.get("/api/v1/reports/performance", headers=supervisor).json()
    assert (
        figures["executives"][0]["figures"]["questions_accepted"],
        figures["executives"][0]["figures"]["questions_skipped"],
    ) == (2, 1)

    assert choose("x", "ignored").status_code == 422
    assert client.post(path, json={"question": "", "target_category": "Cost", "outcome": "skipped"}, headers=asha).status_code == 422
    assert (
        client.post(
            "/api/v1/calls/nope/question-outcomes",
            json={"question": "x", "target_category": "Cost", "outcome": "skipped"},
            headers=asha,
        ).status_code
        == 404
    )
    assert client.get(path).status_code == 401
