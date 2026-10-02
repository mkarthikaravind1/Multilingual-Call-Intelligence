"""Escalation intelligence: detection rules, the optional LLM detector, the
escalation lifecycle, and its API through the real composition root."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.ai.complaint.provider import ComplaintDetectionProvider, ComplaintDetectionResult
from app.ai.escalation.llm_provider import HybridEscalationProvider, LLMEscalationProvider
from app.ai.escalation.provider import EscalationContext, EscalationDetectionProvider
from app.ai.escalation.rule_based_provider import RuleBasedEscalationProvider
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
)
from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.composition.providers import create_escalation_provider
from app.core.config import Settings
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.escalation import (
    Escalation,
    EscalationAssessment,
    EscalationLevel,
    EscalationSignal,
    EscalationSignalType,
    EscalationStatus,
    EscalationTransitionError,
    merge_signals,
)
from app.domain.user import User, UserRole
from app.domain.utterance import SpeakerRole, Utterance
from app.security.jwt import create_access_token
from app.services.escalation_repository import InMemoryEscalationRepository
from app.services.escalation_service import EscalationService

NEUTRAL = SentimentResult(SentimentLabel.NEUTRAL, 0.6, "Calm.")
ANGRY = SentimentResult(SentimentLabel.NEGATIVE, 0.9, "Customer is angry about the delay.")


def conversation(*turns: tuple[SpeakerRole, str], call_id: str = "call-1") -> Conversation:
    result = Conversation(call_id=call_id)
    for index, (role, text) in enumerate(turns):
        result.add_utterance(
            Utterance(
                utterance_id=f"u{index}",
                transcript=text,
                speaker_role=role,
                languages=("en",),
                start_time=float(index),
                end_time=float(index) + 1,
            )
        )
    return result


def coverage(*statuses: tuple[str, ComplaintCoverageStatus], call_id: str = "call-1"):
    result = ConversationCoverage(call_id=call_id)
    steps = {
        ComplaintCoverageStatus.DETECTED: ("detect",),
        ComplaintCoverageStatus.PROBED: ("detect", "probe"),
        ComplaintCoverageStatus.UNRESOLVED: ("detect", "probe", "cover", "mark_unresolved"),
    }
    for category, status in statuses:
        complaint = result.add(category)
        for step in steps[status]:
            getattr(complaint, step)()
    return result


def assess(*turns, sentiment=NEUTRAL, complaints=()) -> EscalationAssessment:
    return RuleBasedEscalationProvider().assess(
        EscalationContext(conversation(*turns), coverage(*complaints), sentiment)
    )


def types(assessment: EscalationAssessment) -> set[EscalationSignalType]:
    return {signal.signal_type for signal in assessment.signals}


CUSTOMER = SpeakerRole.CUSTOMER
ICR = SpeakerRole.ICR


# ---- Rule-based detection ----

def test_calm_call_is_not_escalated():
    result = assess((CUSTOMER, "When will my car be ready?"))

    assert result.level is EscalationLevel.NONE
    assert result.signals == ()


@pytest.mark.parametrize(
    "text, signal_type, level",
    [
        ("I want to speak to your manager right now.", EscalationSignalType.MANAGER_REQUEST, EscalationLevel.HIGH),
        ("Please escalate this.", EscalationSignalType.MANAGER_REQUEST, EscalationLevel.HIGH),
        ("I will take you to consumer court.", EscalationSignalType.LEGAL_THREAT, EscalationLevel.CRITICAL),
        ("My lawyer will send a legal notice.", EscalationSignalType.LEGAL_THREAT, EscalationLevel.CRITICAL),
        ("I'm going to post this on social media.", EscalationSignalType.PUBLIC_COMPLAINT, EscalationLevel.HIGH),
        ("Just cancel it and give me a refund.", EscalationSignalType.CANCELLATION, EscalationLevel.HIGH),
    ],
)
def test_customer_phrases_raise_signals(text, signal_type, level):
    result = assess((CUSTOMER, text))

    assert types(result) == {signal_type}
    assert result.level is level
    assert result.signals[0].evidence == text


def test_native_script_loanwords_are_recognised():
    result = assess((CUSTOMER, "உங்க மேனேஜர் கிட்ட பேசணும்"))  # Tamil: "I need to talk to your manager"

    assert types(result) == {EscalationSignalType.MANAGER_REQUEST}


def test_unknown_speaker_counts_as_the_customer():
    assert types(assess((SpeakerRole.UNKNOWN, "Get me your supervisor."))) == {
        EscalationSignalType.MANAGER_REQUEST
    }


def test_what_the_icr_says_is_ignored():
    result = assess((ICR, "I can connect you to my manager or process a refund."))

    assert result.level is EscalationLevel.NONE


def test_words_inside_other_words_do_not_match():
    assert assess((CUSTOMER, "Thanks for the courtesy call about the courtyard.")).level is EscalationLevel.NONE


def test_clearly_negative_tone_is_a_watch():
    result = assess((CUSTOMER, "This is taking too long."), sentiment=ANGRY)

    assert types(result) == {EscalationSignalType.NEGATIVE_TONE}
    assert result.level is EscalationLevel.WATCH


def test_mildly_negative_tone_is_ignored():
    mild = SentimentResult(SentimentLabel.NEGATIVE, 0.6, "A little unhappy.")

    assert assess((CUSTOMER, "Hmm."), sentiment=mild).level is EscalationLevel.NONE


def test_open_or_unresolved_complaints_are_a_watch():
    two_open = assess(
        (CUSTOMER, "Late and nobody called."),
        complaints=(
            ("Turnaround Time", ComplaintCoverageStatus.DETECTED),
            ("Communication", ComplaintCoverageStatus.PROBED),
        ),
    )
    unresolved = assess(
        (CUSTOMER, "Still not fixed."),
        complaints=(("Service Quality", ComplaintCoverageStatus.UNRESOLVED),),
    )
    one_open = assess(
        (CUSTOMER, "Late."), complaints=(("Turnaround Time", ComplaintCoverageStatus.DETECTED),)
    )

    assert types(two_open) == {EscalationSignalType.UNRESOLVED_COMPLAINTS}
    assert "Service Quality" in unresolved.signals[0].description
    assert one_open.level is EscalationLevel.NONE


def test_two_concerns_together_step_the_level_up():
    watches = assess(
        (CUSTOMER, "This is ridiculous."),
        sentiment=ANGRY,
        complaints=(("Service Quality", ComplaintCoverageStatus.UNRESOLVED),),
    )
    highs = assess((CUSTOMER, "Cancel my booking, I want my manager."))

    assert watches.level is EscalationLevel.HIGH
    assert highs.level is EscalationLevel.CRITICAL


# ---- LLM detector (optional) ----

class FakeLLM(LLMClient):
    def __init__(self, text: str = '{"signals": []}', error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.error:
            raise self.error
        return LLMResponse(self.text)


LLM_SIGNAL = json.dumps(
    {
        "signals": [
            {
                "type": "legal_threat",
                "level": "critical",
                "description": "Customer said they will go to the consumer forum.",
                "evidence": "நுகர்வோர் மன்றத்துக்கு போவேன்",
            }
        ]
    }
)


def context(*turns) -> EscalationContext:
    return EscalationContext(conversation(*turns), coverage(), NEUTRAL)


def test_llm_detector_parses_signals_and_sees_the_call():
    llm = FakeLLM(LLM_SIGNAL)

    result = LLMEscalationProvider(llm).assess(context((CUSTOMER, "நுகர்வோர் மன்றத்துக்கு போவேன்")))

    assert result.level is EscalationLevel.CRITICAL
    assert result.signals[0].evidence == "நுகர்வோர் மன்றத்துக்கு போவேன்"
    prompt = llm.requests[0].prompt
    assert "CUSTOMER: நுகர்வோர் மன்றத்துக்கு போவேன்" in prompt
    assert "Customer tone: NEUTRAL" in prompt


@pytest.mark.parametrize(
    "text",
    ["not json", '{"signals": "x"}', '{"signals": [{"type": "mood", "level": "high", "description": "x"}]}', "[]"],
)
def test_invalid_llm_output_is_discarded(text):
    assert LLMEscalationProvider(FakeLLM(text)).assess(context((CUSTOMER, "Hi"))).level is EscalationLevel.NONE


def test_hybrid_adds_what_the_rules_miss():
    hybrid = HybridEscalationProvider(RuleBasedEscalationProvider(), LLMEscalationProvider(FakeLLM(LLM_SIGNAL)))

    result = hybrid.assess(context((CUSTOMER, "Cancel it, I want a refund.")))

    assert types(result) == {EscalationSignalType.CANCELLATION, EscalationSignalType.LEGAL_THREAT}
    assert result.level is EscalationLevel.CRITICAL


def test_hybrid_keeps_the_rules_when_the_llm_fails():
    hybrid = HybridEscalationProvider(
        RuleBasedEscalationProvider(), LLMEscalationProvider(FakeLLM(error=RuntimeError("down")))
    )

    result = hybrid.assess(context((CUSTOMER, "Let me speak to your manager.")))

    assert types(result) == {EscalationSignalType.MANAGER_REQUEST}


def test_escalation_provider_factory():
    rules = Settings(_env_file=None)  # type: ignore[call-arg]
    llm = Settings(_env_file=None, escalation_provider="llm")  # type: ignore[call-arg]
    bad = Settings(_env_file=None, escalation_provider="magic")  # type: ignore[call-arg]

    assert isinstance(create_escalation_provider(settings=rules), RuleBasedEscalationProvider)
    assert isinstance(create_escalation_provider(FakeLLM(), llm), HybridEscalationProvider)
    with pytest.raises(Exception, match="Unsupported escalation provider"):
        create_escalation_provider(settings=bad)


# ---- Lifecycle ----

def signal(signal_type=EscalationSignalType.NEGATIVE_TONE, level=EscalationLevel.WATCH):
    return EscalationSignal(signal_type, level, f"{signal_type.value} signal")


def escalation(level=EscalationLevel.WATCH, status=EscalationStatus.OPEN, **extra) -> Escalation:
    return Escalation(
        call_id="call-1",
        level=level,
        signals=(signal(level=level),),
        status=status,
        first_detected_at=10.0,
        updated_at=10.0,
        **extra,
    )


def test_level_only_rises():
    high = escalation(EscalationLevel.HIGH)

    lower = high.raise_with(EscalationAssessment(EscalationLevel.WATCH, (signal(),)), 20.0)
    higher = high.raise_with(
        EscalationAssessment(
            EscalationLevel.CRITICAL,
            (signal(EscalationSignalType.LEGAL_THREAT, EscalationLevel.CRITICAL),),
        ),
        30.0,
    )

    assert lower.level is EscalationLevel.HIGH
    assert higher.level is EscalationLevel.CRITICAL
    assert higher.updated_at == 30.0


def test_unchanged_assessment_returns_the_same_record():
    current = escalation()

    assert current.raise_with(EscalationAssessment(EscalationLevel.WATCH, (signal(),)), 99.0) is current


def test_merge_keeps_one_signal_per_type_highest_first():
    merged = merge_signals(
        (signal(),),
        (signal(EscalationSignalType.MANAGER_REQUEST, EscalationLevel.HIGH), signal()),
    )

    assert [s.signal_type for s in merged] == [
        EscalationSignalType.MANAGER_REQUEST,
        EscalationSignalType.NEGATIVE_TONE,
    ]


def test_acknowledge_and_resolve():
    acknowledged = escalation().acknowledge("sup@example.com", 20.0)
    resolved = acknowledged.resolve("sup@example.com", 30.0, "  Called the customer back.  ")

    assert acknowledged.status is EscalationStatus.ACKNOWLEDGED
    assert acknowledged.acknowledged_by == "sup@example.com"
    assert resolved.status is EscalationStatus.RESOLVED
    assert resolved.resolution_note == "Called the customer back."
    with pytest.raises(EscalationTransitionError):
        acknowledged.acknowledge("sup@example.com", 40.0)
    with pytest.raises(EscalationTransitionError):
        resolved.resolve("sup@example.com", 40.0)


def test_open_escalation_can_be_resolved_directly():
    assert escalation().resolve("sup@example.com", 20.0).status is EscalationStatus.RESOLVED


def test_a_higher_level_reopens_a_resolved_escalation():
    resolved = escalation(EscalationLevel.HIGH).resolve("sup@example.com", 20.0, "Handled")
    same = resolved.raise_with(
        EscalationAssessment(EscalationLevel.HIGH, (signal(level=EscalationLevel.HIGH),)), 30.0
    )
    critical = resolved.raise_with(
        EscalationAssessment(
            EscalationLevel.CRITICAL,
            (signal(EscalationSignalType.LEGAL_THREAT, EscalationLevel.CRITICAL),),
        ),
        40.0,
    )

    assert same.status is EscalationStatus.RESOLVED
    assert critical.status is EscalationStatus.OPEN
    assert critical.resolution_note is None and critical.resolved_by is None


# ---- Service ----

class CountingProvider(EscalationDetectionProvider):
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error
        self._rules = RuleBasedEscalationProvider()

    def assess(self, context):
        self.calls += 1
        if self.error:
            raise self.error
        return self._rules.assess(context)


def test_service_creates_raises_and_ignores_calm_calls():
    service = EscalationService(InMemoryEscalationRepository(), RuleBasedEscalationProvider(), clock=lambda: 50.0)
    calm = conversation((CUSTOMER, "Hello"), call_id="calm")

    assert service.assess(calm, coverage(call_id="calm"), NEUTRAL) is None
    first = service.assess(conversation((CUSTOMER, "Refund me.")), coverage(), NEUTRAL)
    second = service.assess(
        conversation((CUSTOMER, "Refund me."), (CUSTOMER, "Or I go to consumer court.")),
        coverage(),
        NEUTRAL,
    )

    assert first.level is EscalationLevel.HIGH and first.status is EscalationStatus.OPEN
    assert second.level is EscalationLevel.CRITICAL
    assert service.get("call-1") == second


def test_detector_failure_never_breaks_the_call():
    service = EscalationService(InMemoryEscalationRepository(), CountingProvider(RuntimeError("boom")))

    assert service.assess(conversation((CUSTOMER, "Refund")), coverage(), NEUTRAL) is None


def test_queue_is_most_severe_then_oldest_first():
    repository = InMemoryEscalationRepository()
    service = EscalationService(repository, RuleBasedEscalationProvider())
    for call_id, level, detected in (
        ("watch-old", EscalationLevel.WATCH, 1.0),
        ("critical", EscalationLevel.CRITICAL, 5.0),
        ("high-new", EscalationLevel.HIGH, 9.0),
        ("high-old", EscalationLevel.HIGH, 2.0),
    ):
        repository.save(
            Escalation(call_id, level, (signal(level=level),), EscalationStatus.OPEN, detected, detected)
        )
    service.resolve("watch-old", "sup@example.com")

    assert [e.call_id for e in service.list_queue()] == ["critical", "high-old", "high-new"]
    assert [e.call_id for e in service.list_queue(active=False)] == ["watch-old"]


# ---- Through the API ----

class _Complaints(ComplaintDetectionProvider):
    def detect(self, conversation, learning_context=()):
        return [ComplaintDetectionResult("Turnaround Time", 0.9, "The car was late.")]


class _Sentiment(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEGATIVE, 0.9, "Angry about the delay.")


class _Questions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


def _client(app, role: UserRole) -> TestClient:
    user = User(
        user_id=f"user-{role.value}",
        email=f"{role.value.lower()}@example.com",
        password_hash="unused",
        role=role,
        is_active=True,
        created_at=time.time(),
    )
    app.state.services.user_repository.save(user)
    return TestClient(app, headers={"Authorization": f"Bearer {create_access_token(user)}"})


@pytest.fixture
def api():
    provider = CountingProvider()
    services = build_api_services(
        _Complaints(),
        _Sentiment(),
        _Questions(),
        Settings(_env_file=None),  # type: ignore[call-arg]
        escalation_provider=provider,
    )
    app = create_app(services)
    return _client(app, UserRole.ICR), _client(app, UserRole.SUPERVISOR), provider


def _say(client: TestClient, call_id: str, index: int, text: str) -> dict:
    response = client.post(
        f"/api/v1/calls/{call_id}/utterances",
        json={
            "utterance_id": f"{call_id}-{index}",
            "transcript": text,
            "speaker_role": "CUSTOMER",
            "languages": ["en"],
            "start_time": float(index),
            "end_time": index + 1.0,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_new_speech_is_assessed_and_the_analysis_carries_the_escalation(api):
    icr, _, _ = api
    icr.post("/api/v1/calls", json={"call_id": "c1"})

    body = _say(icr, "c1", 0, "This is the third time. Let me talk to your manager.")

    escalation = body["escalation"]
    assert escalation["level"] == "critical"  # manager request + negative tone
    assert escalation["status"] == "open"
    assert {s["signal_type"] for s in escalation["signals"]} >= {"manager_request", "negative_tone"}


def test_reading_the_analysis_never_reruns_detection(api):
    icr, _, provider = api
    icr.post("/api/v1/calls", json={"call_id": "c2"})
    _say(icr, "c2", 0, "I want a refund.")
    calls_after_speech = provider.calls

    first = icr.get("/api/v1/calls/c2/analysis").json()
    second = icr.get("/api/v1/calls/c2/analysis").json()

    assert provider.calls == calls_after_speech
    assert first["escalation"] == second["escalation"]
    assert first["escalation"]["level"] in {"high", "critical"}


def test_completed_call_keeps_its_escalation(api):
    icr, _, _ = api
    icr.post("/api/v1/calls", json={"call_id": "c3"})
    _say(icr, "c3", 0, "I will post this on social media.")
    icr.post("/api/v1/calls/c3/complete", json={"end_time": 10.0})

    assert icr.get("/api/v1/calls/c3/analysis").json()["escalation"]["status"] == "open"


def test_calm_calls_have_no_escalation(api):
    icr, _, _ = api
    icr.post("/api/v1/calls", json={"call_id": "calm"})

    # Negative tone alone is only a watch-level concern for this fake sentiment.
    body = _say(icr, "calm", 0, "When will it be ready?")

    assert body["escalation"]["level"] == "watch"
    icr.post("/api/v1/calls", json={"call_id": "quiet"})
    assert icr.get("/api/v1/calls/quiet/analysis").json()["escalation"] is None


def test_call_history_flags_escalated_calls(api):
    icr, _, _ = api
    icr.post("/api/v1/calls", json={"call_id": "flagged"})
    icr.post("/api/v1/calls", json={"call_id": "plain"})
    _say(icr, "flagged", 0, "Cancel my booking.")

    items = {item["call_id"]: item for item in icr.get("/api/v1/calls").json()["items"]}

    assert items["flagged"]["escalation_level"] in {"high", "critical"}
    assert items["flagged"]["escalation_status"] == "open"
    assert items["plain"]["escalation_level"] is None


def test_supervisor_works_the_queue(api):
    icr, supervisor, _ = api
    icr.post("/api/v1/calls", json={"call_id": "q1"})
    _say(icr, "q1", 0, "I'm taking you to consumer court.")

    assert icr.get("/api/v1/escalations").status_code == 403
    (item,) = supervisor.get("/api/v1/escalations").json()
    assert item["call_id"] == "q1" and item["level"] == "critical"

    acknowledged = supervisor.post("/api/v1/escalations/q1/acknowledge")
    assert acknowledged.status_code == 200
    assert acknowledged.json()["acknowledged_by"] == "supervisor@example.com"
    assert supervisor.post("/api/v1/escalations/q1/acknowledge").status_code == 409
    assert icr.post("/api/v1/escalations/q1/resolve", json={}).status_code == 403

    resolved = supervisor.post("/api/v1/escalations/q1/resolve", json={"note": "Called back, offered a discount."})
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolution_note"] == "Called back, offered a discount."
    assert supervisor.get("/api/v1/escalations").json() == []
    assert [e["call_id"] for e in supervisor.get("/api/v1/escalations?state=resolved").json()] == ["q1"]
    assert supervisor.post("/api/v1/escalations/q1/resolve", json={}).status_code == 409


def test_live_websocket_analysis_carries_the_escalation(api):
    icr, _, _ = api
    icr.post("/api/v1/calls", json={"call_id": "ws-1"})
    ticket = icr.post("/api/v1/calls/ws-1/live-token").json()["token"]

    with icr.websocket_connect(f"/api/v1/calls/ws-1/live?ticket={ticket}") as ws:
        ws.send_text(
            json.dumps(
                {
                    "type": "utterance",
                    "utterance_id": "ws-1-u0",
                    "transcript": "I will complain on social media about this.",
                    "speaker_role": "CUSTOMER",
                    "languages": ["en"],
                    "start_time": 0.0,
                    "end_time": 3.0,
                }
            )
        )
        event = ws.receive_json()

    assert event["type"] == "analysis"
    assert "public_complaint" in {s["signal_type"] for s in event["escalation"]["signals"]}


def test_unknown_escalation_returns_404(api):
    _, supervisor, _ = api

    assert supervisor.post("/api/v1/escalations/missing/acknowledge").status_code == 404
