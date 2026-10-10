"""Live analysis shared between API instances through the LiveStateStore.

Each test builds two CallWorkflowService instances ("A" and "B") that share
only what a multi-instance deployment shares: the database repositories and
the live state store (Redis in production).
"""

from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.ai.complaint.provider import ComplaintDetectionProvider, ComplaintDetectionResult
from app.ai.question.provider import QuestionGenerationContext, QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentLabel, SentimentResult
from app.ai.summary.rule_based_provider import RuleBasedSummaryProvider
from app.domain.conversation import Conversation
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource
from app.domain.service_estimate import CallServiceEstimate, EstimatedPart, LabourEstimate, ServiceEstimate
from app.domain.utterance import SpeakerRole, Utterance
from app.estimation.default_pricing import DEFAULT_PRICING_CONFIG
from app.estimation.rule_based_provider import RuleBasedEstimationProvider
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
from app.services.live_analysis_store import LiveAnalysisSnapshot, LiveAnalysisStore
from app.services.live_state_store import (
    InMemoryLiveStateStore,
    LiveStateStore,
    RedisLiveStateStore,
)
from app.services.next_question_service import NextQuestionService
from app.services.post_call_summary_repository import InMemoryPostCallSummaryRepository
from app.services.post_call_summary_service import PostCallSummaryService
from app.services.sentiment_analysis_service import SentimentAnalysisService

CALL_ID = "call-1"
_SENTIMENT = SentimentResult(SentimentLabel.NEGATIVE, 0.9, "The customer is unhappy.")


class _Complaints(ComplaintDetectionProvider):
    def detect(self, conversation: Conversation, learning_context=()):
        return [ComplaintDetectionResult("Turnaround Time", 0.9, "Late again.")]


class _Sentiment(SentimentAnalysisProvider):
    def analyze(self, conversation: Conversation, learning_context=()):
        return _SENTIMENT


class _Questions(QuestionSuggestionProvider):
    def generate(self, context: QuestionGenerationContext, learning_context=()):
        return QuestionSuggestion(
            question="When was the vehicle promised?",
            target_category=context.category,
            priority=1,
            reason="Turnaround is still open.",
            source=SuggestionSource.LLM,
            confidence=0.8,
        )


class FakeRedis:
    """Enough of redis-py for RedisLiveStateStore; returns bytes like redis-py."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = value.encode("utf-8")
        return True

    def delete(self, key):
        self.data.pop(key, None)

    def eval(self, script, numkeys, key, token):
        return 0

    def ping(self):
        return True


class BrokenStore(LiveStateStore):
    """A live state store whose backend (e.g. Redis) is down."""

    def get_json(self, key):
        raise ConnectionError("redis down")

    def set_json(self, key, value, ttl_seconds=None):
        raise ConnectionError("redis down")

    def delete(self, key):
        raise ConnectionError("redis down")

    def acquire_lock(self, name, ttl_seconds):
        raise ConnectionError("redis down")

    def release_lock(self, name, token):
        raise ConnectionError("redis down")


@dataclass
class _Cluster:
    a: CallWorkflowService
    b: CallWorkflowService
    call_service: CallService


def _workflow(call_service, coverage, summaries, store, ttl=3600.0) -> CallWorkflowService:
    return CallWorkflowService(
        call_service,
        coverage,
        ConversationAnalysisService(
            ComplaintAnalysisService(_Complaints()),
            SentimentAnalysisService(_Sentiment()),
        ),
        NextQuestionService(_Questions()),
        EstimationService(RuleBasedEstimationProvider(DEFAULT_PRICING_CONFIG)),
        PostCallSummaryService(RuleBasedSummaryProvider()),
        post_call_summary_repository=summaries,
        live_state_store=store,
        live_analysis_ttl_seconds=ttl,
    )


def _cluster(store_a: LiveStateStore, store_b: LiveStateStore | None = None, ttl=3600.0):
    # Shared database (conversations + coverage), as in production.
    call_service = CallService(ConversationService(InMemoryConversationRepository()))
    coverage = InMemoryConversationCoverageRepository()
    summaries = InMemoryPostCallSummaryRepository()
    call_service.start_call(CALL_ID)
    return _Cluster(
        a=_workflow(call_service, coverage, summaries, store_a, ttl),
        b=_workflow(call_service, coverage, summaries, store_b or store_a, ttl),
        call_service=call_service,
    )


def _utterance(index: int = 0, text: str = "My brake pads squeal and the car is late.") -> Utterance:
    return Utterance(
        utterance_id=str(index + 1),
        transcript=text,
        speaker_role=SpeakerRole.CUSTOMER,
        languages=("en",),
        start_time=index * 5.0,
        end_time=index * 5.0 + 4.0,
    )


@pytest.fixture(params=["memory", "redis"])
def shared_store(request) -> LiveStateStore:
    if request.param == "memory":
        return InMemoryLiveStateStore()
    return RedisLiveStateStore(FakeRedis(), "test")


def test_live_analysis_written_by_one_instance_is_read_by_another(shared_store):
    cluster = _cluster(shared_store)

    written = cluster.a.process_utterance(CALL_ID, _utterance())
    read = cluster.b.analyze_call(CALL_ID)

    assert read.sentiment == _SENTIMENT == written.sentiment
    assert read.question_suggestion == written.question_suggestion
    assert read.question_suggestion.source is SuggestionSource.LLM
    assert read.service_estimate == written.service_estimate
    assert read.service_estimate.service_names == ("Brake Pad Replacement",)
    assert read.service_estimate.estimated_cost == written.service_estimate.estimated_cost
    assert [c.category for c in read.coverage.complaints] == ["Turnaround Time"]


def test_without_shared_state_another_instance_sees_no_live_fields():
    # Two separate in-memory stores reproduce the old per-process behaviour.
    cluster = _cluster(InMemoryLiveStateStore(), InMemoryLiveStateStore())

    cluster.a.process_utterance(CALL_ID, _utterance())
    read = cluster.b.analyze_call(CALL_ID)

    assert read.sentiment is None and read.question_suggestion is None


def test_missing_live_state_returns_stored_coverage_only(shared_store):
    cluster = _cluster(shared_store)

    read = cluster.b.analyze_call(CALL_ID)

    assert read.sentiment is None
    assert read.question_suggestion is None
    assert read.service_estimate is None
    assert read.coverage.call_id == CALL_ID


def test_expired_live_state_is_not_returned():
    now = [1000.0]
    store = InMemoryLiveStateStore(clock=lambda: now[0])
    cluster = _cluster(store, ttl=60.0)
    cluster.a.process_utterance(CALL_ID, _utterance())

    now[0] += 59
    assert cluster.b.analyze_call(CALL_ID).sentiment == _SENTIMENT
    now[0] += 2
    expired = cluster.b.analyze_call(CALL_ID)

    assert expired.sentiment is None and expired.service_estimate is None
    assert cluster.b.live_revision(CALL_ID) is None


def test_new_speech_refreshes_the_expiry():
    now = [1000.0]
    store = InMemoryLiveStateStore(clock=lambda: now[0])
    cluster = _cluster(store, ttl=60.0)
    cluster.a.process_utterance(CALL_ID, _utterance(0))
    now[0] += 50
    cluster.b.process_utterance(CALL_ID, _utterance(1))
    now[0] += 50

    assert cluster.a.analyze_call(CALL_ID).sentiment == _SENTIMENT


def test_store_failure_never_fails_a_call():
    cluster = _cluster(BrokenStore())

    processed = cluster.a.process_utterance(CALL_ID, _utterance())
    read = cluster.b.analyze_call(CALL_ID)

    # The utterance and its analysis still go through; reads fall back to
    # what the database holds.
    assert processed.sentiment == _SENTIMENT
    assert cluster.call_service.get_call(CALL_ID).utterance_count == 1
    assert read.sentiment is None
    assert [c.category for c in read.coverage.complaints] == ["Turnaround Time"]
    assert cluster.b.live_revision(CALL_ID) is None


def test_completion_drops_live_state_and_changes_the_revision(shared_store):
    cluster = _cluster(shared_store)
    cluster.a.process_utterance(CALL_ID, _utterance())
    before = cluster.b.live_revision(CALL_ID)

    cluster.a.complete_call(CALL_ID, 99.0)

    assert cluster.b.live_revision(CALL_ID) not in (None, before)
    assert LiveAnalysisStore(shared_store).load(CALL_ID) is None
    completed = cluster.b.analyze_call(CALL_ID)
    assert completed.post_call_summary is not None


def test_revision_changes_on_speech_but_not_on_reads(shared_store):
    cluster = _cluster(shared_store)
    assert cluster.a.live_revision(CALL_ID) is None

    cluster.a.process_utterance(CALL_ID, _utterance(0))
    first = cluster.b.live_revision(CALL_ID)
    cluster.b.analyze_call(CALL_ID)
    assert cluster.a.live_revision(CALL_ID) == first

    cluster.b.process_utterance(CALL_ID, _utterance(1))
    assert cluster.a.live_revision(CALL_ID) not in (None, first)


def test_snapshot_round_trips_every_field(shared_store):
    snapshot = LiveAnalysisSnapshot(
        sentiment=SentimentResult(SentimentLabel.POSITIVE, 0.75, "Thanks a lot."),
        question_suggestions=(
            QuestionSuggestion(
                question="Anything else?",
                target_category="Communication",
                priority=2,
                reason="Wrap up.",
                source=SuggestionSource.RULE_BASED,
                confidence=None,
            ),
        ),
        service_estimate=CallServiceEstimate(
            currency="INR",
            services=(
                ServiceEstimate(
                    service_name="Custom",
                    currency="INR",
                    parts=(EstimatedPart("Part", 2, Decimal("10.55")),),
                    labour=LabourEstimate(1.25, Decimal("600")),
                    estimated_duration_hours=2.0,
                ),
            ),
        ),
    )
    store = LiveAnalysisStore(shared_store)

    store.save(CALL_ID, snapshot)

    assert store.load(CALL_ID) == snapshot


def test_unreadable_live_state_is_ignored():
    raw = InMemoryLiveStateStore()
    raw.set_json(f"live_analysis:{CALL_ID}", {"v": 1, "sentiment": {"label": "ANGRY"}})

    assert LiveAnalysisStore(raw).load(CALL_ID) is None
    raw.set_json(f"live_analysis:{CALL_ID}", {"v": 999})
    assert LiveAnalysisStore(raw).load(CALL_ID) is None
