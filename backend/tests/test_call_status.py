"""The three status indicators and "On Hold": where a call stands (incoming,
outgoing, connected, on hold, ended), what the AI is doing with it, and
where its record stands; what a hold does (nothing is transcribed), and how
holds are kept."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.ai.complaint.provider import ComplaintDetectionProvider, ComplaintDetectionResult
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.question.rule_based_provider import RuleBasedQuestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentLabel, SentimentResult
from app.ai.summary.rule_based_provider import RuleBasedSummaryProvider
from app.api.app_factory import create_app
from app.api.v1.telephony_ws import _process_chunk
from app.api.wiring import build_api_services
from app.core.config import Settings
from app.domain.conversation import (
    CallDirection,
    CallPhase,
    Conversation,
    ConversationAlreadyCompletedError,
    ConversationStatus,
    HoldPeriod,
    call_phase,
)
from app.domain.user import User, UserRole
from app.domain.utterance import SpeakerRole, Utterance
from app.estimation.default_pricing import DEFAULT_PRICING_CONFIG
from app.estimation.rule_based_provider import RuleBasedEstimationProvider
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import build_session_factory
from app.infrastructure.database.repositories.call_listing_query import (
    PostgresCallListingQuery,
)
from app.infrastructure.database.repositories.conversation_repository import (
    PostgresConversationRepository,
)
from app.security.jwt import create_access_token
from app.services.call_alerts import CallAlertService, InMemoryCallAlertRepository
from app.services.call_indicators import AiStatus, CallIndicators, LoggingStatus
from app.services.call_listing import CallListFilters, CallListItem
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.conversation_analysis_service import ConversationAnalysisService
from app.services.conversation_service import ConversationService
from app.services.estimation_service import EstimationService
from app.services.in_memory_conversation_coverage_repository import (
    InMemoryConversationCoverageRepository,
)
from app.services.in_memory_conversation_repository import InMemoryConversationRepository
from app.services.live_analysis_store import LiveAnalysisStore
from app.services.live_state_store import InMemoryLiveStateStore
from app.services.next_question_service import NextQuestionService
from app.services.post_call_summary_service import PostCallSummaryService
from app.services.sentiment_analysis_service import SentimentAnalysisService
from app.services.telephony_audio_buffer import BufferedAudioChunk

CALL_ID = "call-1"
INBOUND, OUTBOUND = CallDirection.INBOUND, CallDirection.OUTBOUND


def _line(index: int = 1, text: str = "The bill was too high.") -> Utterance:
    return Utterance(f"u{index}", text, SpeakerRole.CUSTOMER, ("en",), float(index), index + 0.5)


# ---- Where the call stands ----


@pytest.mark.parametrize(
    ("direction", "answered", "on_hold", "phase"),
    [
        (INBOUND, False, False, CallPhase.INCOMING),
        (OUTBOUND, False, False, CallPhase.OUTGOING),
        (None, False, False, CallPhase.INCOMING),
        (INBOUND, True, False, CallPhase.CONNECTED),
        (OUTBOUND, True, False, CallPhase.CONNECTED),
        (INBOUND, True, True, CallPhase.ON_HOLD),
    ],
)
def test_an_active_call_is_ringing_connected_or_on_hold(direction, answered, on_hold, phase):
    assert call_phase(ConversationStatus.ACTIVE, direction, answered, on_hold) is phase
    # Whatever it was doing, a completed call has ended.
    assert call_phase(ConversationStatus.COMPLETED, direction, answered, on_hold) is CallPhase.ENDED


def test_a_call_is_connected_once_an_executive_is_on_it_or_something_is_said():
    ringing = Conversation(CALL_ID, direction=INBOUND)
    assert ringing.phase is CallPhase.INCOMING
    assert Conversation(CALL_ID, direction=OUTBOUND).phase is CallPhase.OUTGOING

    ringing.assign("asha")
    assert ringing.phase is CallPhase.CONNECTED

    # Nobody could be matched to this phone call, but it is being talked on.
    unmatched = Conversation(CALL_ID, direction=INBOUND)
    unmatched.add_utterance(_line())
    assert unmatched.phase is CallPhase.CONNECTED


# ---- On hold ----


def test_a_call_goes_on_hold_and_comes_back_and_keeps_each_hold():
    call = Conversation(CALL_ID, direction=INBOUND, executive_user_id="asha")

    assert call.hold(100.0) is True
    assert (call.on_hold, call.phase, call.hold_seconds) == (True, CallPhase.ON_HOLD, 0.0)
    assert call.hold(105.0) is False  # already on hold: the first start stands
    assert call.resume(130.0) is True
    assert (call.on_hold, call.phase, call.hold_seconds) == (False, CallPhase.CONNECTED, 30.0)
    assert call.resume(140.0) is False

    call.hold(200.0)
    call.resume(215.0)
    assert call.holds == (HoldPeriod(100.0, 130.0), HoldPeriod(200.0, 215.0))
    assert call.hold_seconds == 45.0


def test_a_call_that_ends_on_hold_ends_its_hold_too():
    call = Conversation(CALL_ID, start_time=0.0)
    call.hold(50.0)

    call.complete(80.0)

    assert (call.on_hold, call.phase) == (False, CallPhase.ENDED)
    assert call.holds == (HoldPeriod(50.0, 80.0),)
    with pytest.raises(ConversationAlreadyCompletedError):
        call.hold(90.0)


def test_a_hold_never_ends_before_it_started():
    call = Conversation(CALL_ID)
    call.hold(100.0)

    call.resume(90.0)  # a client clock behind the server's

    assert call.holds == (HoldPeriod(100.0, 100.0),)


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield build_session_factory(engine)
    engine.dispose()


def test_holds_are_stored_and_the_call_list_knows_who_is_on_hold(session_factory):
    service = CallService(ConversationService(PostgresConversationRepository(session_factory)))
    service.start_call("held", direction=INBOUND, executive_user_id="asha")
    service.start_call("back", direction=INBOUND, executive_user_id="asha")
    service.start_call("ringing", direction=OUTBOUND)
    service.hold_call("held", 100.0)
    service.hold_call("back", 100.0)
    service.resume_call("back", 160.0)
    # Repeating either changes nothing.
    service.hold_call("held", 120.0)
    service.resume_call("back", 170.0)

    assert service.get_call("held").holds == (HoldPeriod(100.0, None),)
    assert service.get_call("back").holds == (HoldPeriod(100.0, 160.0),)
    assert service.get_call("ringing").holds == ()

    listing = PostgresCallListingQuery(session_factory)
    expected = {
        "held": CallPhase.ON_HOLD,
        "back": CallPhase.CONNECTED,
        "ringing": CallPhase.OUTGOING,
    }
    assert {item.call_id: item.phase for item in listing.active_calls(50)} == expected
    assert {
        item.call_id: item.phase for item in listing.search(CallListFilters(), 50, 0).items
    } == expected


def test_a_listed_call_with_lines_but_no_executive_is_connected():
    item = CallListItem("c", ConversationStatus.ACTIVE, 0.0, None, 3, direction=INBOUND)

    assert item.phase is CallPhase.CONNECTED
    assert CallListItem("c", ConversationStatus.ACTIVE, 0.0, None, 0).phase is CallPhase.INCOMING


# ---- Nothing is transcribed while on hold ----


class _Recording:
    """Stands in for the live chunk pipeline: remembers what it was given."""

    def __init__(self, indicators=None, on_chunk=None) -> None:
        self.chunks = []
        self._on_chunk = on_chunk

    def process_chunk(self, call_id, chunk):
        self.chunks.append(chunk)
        if self._on_chunk is not None:
            self._on_chunk()


def _chunk(has_speech: bool = True) -> BufferedAudioChunk:
    return BufferedAudioChunk(audio=b"wav", start_time=0.0, end_time=4.0, has_speech=has_speech)


def _stream_parts():
    call_service = CallService(ConversationService(InMemoryConversationRepository()))
    call_service.start_call(CALL_ID, direction=INBOUND, executive_user_id="asha")
    state = InMemoryLiveStateStore()
    alerts = CallAlertService(InMemoryCallAlertRepository(), state)
    return call_service, state, alerts, CallIndicators(state)


def test_audio_that_arrives_on_hold_is_not_transcribed_or_counted_as_poor_audio():
    call_service, state, alerts, indicators = _stream_parts()
    pipeline = _Recording()

    def send() -> None:
        asyncio.run(
            _process_chunk(CALL_ID, _chunk(), 0, call_service, pipeline, False, None, alerts, indicators)
        )

    send()
    assert len(pipeline.chunks) == 1

    call_service.hold_call(CALL_ID, 10.0)
    send()
    send()
    assert len(pipeline.chunks) == 1  # hold music never reaches the transcript
    assert state.get_json(f"audio_quality:{CALL_ID}") == [True]

    call_service.resume_call(CALL_ID, 40.0)
    send()
    assert len(pipeline.chunks) == 2


def test_the_ai_is_transcribing_while_a_chunk_with_speech_is_worked_on():
    call_service, _, alerts, indicators = _stream_parts()
    call = call_service.get_call(CALL_ID)
    seen = []
    pipeline = _Recording(on_chunk=lambda: seen.append(indicators.ai(call)))

    for has_speech in (True, False):
        asyncio.run(
            _process_chunk(
                CALL_ID, _chunk(has_speech), 0, call_service, pipeline, False, None, alerts, indicators
            )
        )

    # Silence is not "transcribing".
    assert seen == [AiStatus.TRANSCRIBING, AiStatus.LISTENING]
    assert indicators.ai(call) is AiStatus.LISTENING


# ---- What the AI is doing, and where the record stands ----


class _Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_the_ai_status_is_shared_tells_open_screens_and_runs_out():
    clock = _Clock()
    state = InMemoryLiveStateStore(clock=clock)
    indicators, view = CallIndicators(state, ttl_seconds=30.0), LiveAnalysisStore(state)
    call = Conversation(CALL_ID)
    assert indicators.ai(call) is AiStatus.LISTENING
    assert view.revision(CALL_ID) is None

    indicators.set_ai(CALL_ID, AiStatus.CLASSIFYING_COMPLAINT)

    # Another instance reads the same thing.
    assert CallIndicators(state).ai(call) is AiStatus.CLASSIFYING_COMPLAINT
    revision = view.revision(CALL_ID)
    assert revision is not None
    # Saying the same again tells nobody.
    indicators.set_ai(CALL_ID, AiStatus.CLASSIFYING_COMPLAINT)
    assert view.revision(CALL_ID) == revision

    # A worker that died mid-step does not leave the call "classifying".
    clock.now += 31.0
    assert indicators.ai(call) is AiStatus.LISTENING


def test_nothing_is_listened_to_on_hold_or_after_the_call():
    indicators = CallIndicators(InMemoryLiveStateStore())
    call = Conversation(CALL_ID)
    indicators.set_ai(CALL_ID, AiStatus.TRANSCRIBING)

    call.hold(10.0)
    assert indicators.ai(call) is None
    call.resume(20.0)
    assert indicators.ai(call) is AiStatus.TRANSCRIBING
    call.complete(30.0)
    assert indicators.ai(call) is None


def test_a_failing_store_never_fails_the_work_it_describes():
    class _Down(InMemoryLiveStateStore):
        def get_json(self, key):
            raise RuntimeError("Redis is down")

    indicators = CallIndicators(_Down())

    indicators.set_ai(CALL_ID, AiStatus.TRANSCRIBING)
    assert indicators.ai(Conversation(CALL_ID)) is AiStatus.LISTENING


def test_the_record_goes_from_recording_to_archived_to_export_ready():
    recorded: set[str] = set()
    indicators = CallIndicators(
        InMemoryLiveStateStore(),
        is_being_recorded=lambda call_id: call_id == CALL_ID,
        has_recording=lambda call_id: call_id in recorded,
    )
    call, other = Conversation(CALL_ID), Conversation("manual")

    assert indicators.logging(call, has_summary=False) == (LoggingStatus.RECORDING,)
    assert indicators.logging(other, has_summary=False) == ()

    call.complete(60.0)
    assert indicators.logging(call, has_summary=False) == ()
    recorded.add(CALL_ID)
    assert indicators.logging(call, has_summary=False) == (LoggingStatus.ARCHIVE_COMPLETE,)
    assert indicators.logging(call, has_summary=True) == (
        LoggingStatus.ARCHIVE_COMPLETE,
        LoggingStatus.EXPORT_READY,
    )

    # A server that keeps no recordings: only the export.
    plain = CallIndicators(InMemoryLiveStateStore())
    assert plain.logging(Conversation("c2"), has_summary=False) == ()
    assert plain.logging(call, has_summary=True) == (LoggingStatus.EXPORT_READY,)

    def broken(call_id):
        raise RuntimeError("database is down")

    failing = CallIndicators(InMemoryLiveStateStore(), has_recording=broken)
    assert failing.logging(call, has_summary=True) == (LoggingStatus.EXPORT_READY,)


# ---- Through an analysis ----


class _Complaints(ComplaintDetectionProvider):
    def __init__(self) -> None:
        self.error: Exception | None = None

    def detect(self, conversation, learning_context=()):
        if self.error is not None:
            raise self.error
        return [ComplaintDetectionResult("Cost", 0.9, "The bill was too high.")]


class _Negative(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEGATIVE, 0.8, "Unhappy.")


class _Steps(CallIndicators):
    def __init__(self, state) -> None:
        super().__init__(state)
        self.steps: list[AiStatus] = []

    def set_ai(self, call_id, status):
        self.steps.append(status)
        super().set_ai(call_id, status)


def _workflow():
    state = InMemoryLiveStateStore()
    indicators, complaints = _Steps(state), _Complaints()
    call_service = CallService(ConversationService(InMemoryConversationRepository()))
    call_service.start_call(CALL_ID, direction=INBOUND, executive_user_id="asha")
    workflow = CallWorkflowService(
        call_service,
        InMemoryConversationCoverageRepository(),
        ConversationAnalysisService(
            ComplaintAnalysisService(complaints), SentimentAnalysisService(_Negative())
        ),
        NextQuestionService(RuleBasedQuestionProvider()),
        EstimationService(RuleBasedEstimationProvider(DEFAULT_PRICING_CONFIG)),
        PostCallSummaryService(RuleBasedSummaryProvider()),
        live_state_store=state,
        indicators=indicators,
    )
    return workflow, call_service, indicators, complaints


def test_an_analysis_shows_each_of_its_steps_and_ends_listening():
    workflow, call_service, indicators, _ = _workflow()
    call_service.add_utterance(CALL_ID, _line())

    result = workflow.analyze_latest_speech(CALL_ID)

    assert indicators.steps == [
        AiStatus.CLASSIFYING_COMPLAINT,
        AiStatus.UPDATING_SENTIMENT,
        AiStatus.GENERATING_QUESTION,
        AiStatus.LISTENING,
    ]
    assert result.question_suggestions
    assert workflow.analyze_call(CALL_ID).ai_status is AiStatus.LISTENING


def test_a_failed_analysis_still_ends_listening():
    workflow, call_service, indicators, complaints = _workflow()
    call_service.add_utterance(CALL_ID, _line())
    complaints.error = RuntimeError("the LLM is down")

    with pytest.raises(RuntimeError):
        workflow.analyze_latest_speech(CALL_ID)

    assert indicators.steps == [AiStatus.CLASSIFYING_COMPLAINT, AiStatus.LISTENING]


def test_putting_a_call_on_hold_tells_its_open_screens():
    workflow, _, _, _ = _workflow()
    before = workflow.live_revision(CALL_ID)

    held = workflow.hold_call(CALL_ID, 10.0).phase
    on_hold = workflow.live_revision(CALL_ID)
    resumed = workflow.resume_call(CALL_ID, 25.0).phase

    assert (held, resumed) == (CallPhase.ON_HOLD, CallPhase.CONNECTED)
    assert on_hold not in (None, before)
    assert workflow.live_revision(CALL_ID) != on_hold
    assert workflow.analyze_call(CALL_ID).ai_status is AiStatus.LISTENING


# ---- The API ----


class _NoQuestions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


def _api():
    settings = Settings(_env_file=None, live_calls_cache_seconds=0.0)  # type: ignore[call-arg]
    services = build_api_services(_Complaints(), _Negative(), _NoQuestions(), settings)
    client = TestClient(create_app(services))

    def sign_in(user_id: str, role: UserRole) -> dict[str, str]:
        user = User(user_id, f"{user_id}@example.com", "hash", role, True, time.time())
        services.user_repository.save(user)
        return {"Authorization": f"Bearer {create_access_token(user)}"}

    return client, sign_in


def test_the_executive_holds_and_resumes_a_call_through_the_api():
    client, sign_in = _api()
    asha, supervisor = sign_in("asha", UserRole.ICR), sign_in("sup", UserRole.SUPERVISOR)
    client.post("/api/v1/calls", json={"call_id": "c1", "start_time": None}, headers=asha)

    started = client.get("/api/v1/calls/c1", headers=asha).json()
    assert (started["phase"], started["holds"], started["hold_seconds"]) == ("connected", [], 0.0)
    analysis = client.get("/api/v1/calls/c1/analysis", headers=asha).json()
    assert (analysis["ai_status"], analysis["logging_statuses"]) == ("listening", [])

    held = client.post("/api/v1/calls/c1/hold", headers=asha)
    assert held.status_code == 200
    assert held.json()["phase"] == "on_hold"
    assert held.json()["holds"][0]["ended_at"] is None
    # Asking again changes nothing.
    again = client.post("/api/v1/calls/c1/hold", json={}, headers=asha).json()
    assert again["holds"] == held.json()["holds"]
    assert client.get("/api/v1/calls/c1/analysis", headers=asha).json()["ai_status"] is None
    # A line entered by hand is refused, as the call's audio would be.
    line = {
        "utterance_id": "u1",
        "transcript": "Hello?",
        "speaker_role": "CUSTOMER",
        "languages": ["en"],
        "start_time": 1.0,
        "end_time": 2.0,
    }
    refused = client.post("/api/v1/calls/c1/utterances", json=line, headers=asha)
    assert (refused.status_code, "on hold" in refused.json()["detail"]) == (409, True)
    assert client.get("/api/v1/calls/c1", headers=asha).json()["utterance_count"] == 0

    # The supervisor's live view and the call list show it.
    live = client.get("/api/v1/live-calls", headers=supervisor).json()
    assert [(call["call_id"], call["phase"]) for call in live["items"]] == [("c1", "on_hold")]
    listed = client.get("/api/v1/calls", headers=asha).json()["items"][0]
    assert listed["phase"] == "on_hold"

    start = held.json()["holds"][0]["started_at"]
    resumed = client.post("/api/v1/calls/c1/resume", json={"at": start + 42.0}, headers=asha).json()
    assert (resumed["phase"], resumed["hold_seconds"]) == ("connected", 42.0)
    assert client.post("/api/v1/calls/c1/utterances", json=line, headers=asha).status_code == 200

    client.post("/api/v1/calls/c1/complete", json={}, headers=asha)
    ended = client.get("/api/v1/calls/c1", headers=asha).json()
    assert (ended["phase"], ended["hold_seconds"]) == ("ended", 42.0)
    assert client.get("/api/v1/calls/c1/analysis", headers=asha).json()["ai_status"] is None


def test_a_call_that_has_ended_or_does_not_exist_cannot_be_put_on_hold():
    client, sign_in = _api()
    asha = sign_in("asha", UserRole.ICR)
    client.post("/api/v1/calls", json={"call_id": "c1", "start_time": None}, headers=asha)
    client.post("/api/v1/calls/c1/complete", json={}, headers=asha)

    assert client.post("/api/v1/calls/c1/hold", headers=asha).status_code == 409
    # Nothing to resume: left as it is.
    assert client.post("/api/v1/calls/c1/resume", headers=asha).json()["phase"] == "ended"
    assert client.post("/api/v1/calls/nope/hold", headers=asha).status_code == 404
    assert client.post("/api/v1/calls/c1/hold").status_code == 401
