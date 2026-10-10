"""The supervisor's live view at scale: a fixed number of reads however many
calls are in progress, filters, ordering, paging and the shared cache; the
background sweep that keeps alerts up to date; and the batched reads of the
stores behind them. Calls here are records put straight into the stores:
no call is placed."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentLabel, SentimentResult
from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.core.config import Settings
from app.domain.call_alert import CallAlert, CallAlertType
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import CallDirection, Conversation, ConversationStatus
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.escalation import EscalationLevel, EscalationStatus
from app.domain.user import User, UserRole
from app.domain.utterance import SpeakerRole, Utterance
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import build_session_factory
from app.infrastructure.database.repositories.call_listing_query import (
    PostgresCallListingQuery,
)
from app.infrastructure.database.repositories.conversation_coverage_repository import (
    PostgresConversationCoverageRepository,
)
from app.infrastructure.database.repositories.conversation_repository import (
    PostgresConversationRepository,
)
from app.security.jwt import create_access_token
from app.services.call_alerts import (
    LOW_TRANSCRIPTION_CONFIDENCE,
    CallAlertService,
    InMemoryCallAlertRepository,
)
from app.services.call_listing import CallListingQuery, CallListItem
from app.services.in_memory_conversation_coverage_repository import (
    InMemoryConversationCoverageRepository,
)
from app.services.live_analysis_store import LiveAnalysisSnapshot, LiveAnalysisStore
from app.services.live_calls import LiveAlertSweeper, LiveCallFilters, LiveCallsBoard
from app.services.live_state_store import InMemoryLiveStateStore, RedisLiveStateStore
from app.services.redis_conversation_coverage_repository import (
    RedisConversationCoverageRepository,
)

NOW = 10_000.0


class _Clock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Listing(CallListingQuery):
    """The calls in progress, as given; counts how often it is read."""

    def __init__(self, calls=()) -> None:
        self.calls = list(calls)
        self.reads = 0

    def search(self, filters, limit, offset):
        raise AssertionError("the live view never uses the browsable call list")

    def active_calls(self, limit):
        self.reads += 1
        return tuple(self.calls[:limit])


class _CountingCoverages(InMemoryConversationCoverageRepository):
    def __init__(self) -> None:
        super().__init__()
        self.single_reads = 0
        self.batch_reads = 0

    def get(self, call_id):
        self.single_reads += 1
        return super().get(call_id)

    def get_many(self, call_ids):
        self.batch_reads += 1
        return {c: self._coverages[c] for c in call_ids if c in self._coverages}


class _CountingAlerts(InMemoryCallAlertRepository):
    def __init__(self) -> None:
        super().__init__()
        self.reads = 0
        self.saves = 0

    def list_for_calls(self, call_ids):
        self.reads += 1
        return super().list_for_calls(call_ids)

    def save(self, alert):
        self.saves += 1
        super().save(alert)


class _CountingState(InMemoryLiveStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.single_reads = 0
        self.batch_reads = 0

    def get_json(self, key):
        self.single_reads += 1
        return super().get_json(key)

    def get_many_json(self, keys):
        self.batch_reads += 1
        return [InMemoryLiveStateStore.get_json(self, key) for key in keys]


def _item(call_id: str, start_time: float = NOW - 60, **fields) -> CallListItem:
    return CallListItem(
        call_id=call_id,
        status=ConversationStatus.ACTIVE,
        start_time=start_time,
        end_time=None,
        utterance_count=4,
        direction=CallDirection.INBOUND,
        **fields,
    )


def _coverage(call_id: str, category: str = "Cost", detected_at: float = NOW, confidence=0.9):
    coverage = ConversationCoverage(call_id=call_id)
    complaint = coverage.add(category)
    complaint.status = ComplaintCoverageStatus.DETECTED
    complaint.confidence = confidence
    complaint.detected_at = detected_at
    return coverage


def _tone(label: SentimentLabel) -> LiveAnalysisSnapshot:
    return LiveAnalysisSnapshot(SentimentResult(label, 0.8, "Said so."), (), None)


class _World:
    """A board over in-memory stores that count their reads."""

    def __init__(self, calls=(), cache_seconds: float = 2.0) -> None:
        self.clock = _Clock()
        self.monotonic = _Clock(0.0)
        self.listing = _Listing(calls)
        self.coverages = _CountingCoverages()
        self.state = _CountingState()
        self.analyses = LiveAnalysisStore(self.state)
        self.alert_repository = _CountingAlerts()
        self.alerts = CallAlertService(self.alert_repository, self.state, clock=self.clock)
        self.board = LiveCallsBoard(
            self.listing,
            self.coverages,
            self.analyses,
            self.alerts,
            cache_seconds=cache_seconds,
            clock=self.clock,
            monotonic=self.monotonic,
        )

    def alert(self, call_id: str, subject: str = "Cost", cleared_at=None) -> None:
        self.alert_repository.save(
            CallAlert(
                call_id,
                CallAlertType.UNCOVERED_CATEGORY,
                subject,
                "Not asked about yet.",
                raised_at=NOW,
                cleared_at=cleared_at,
            )
        )

    def page(self, limit: int = 50, offset: int = 0, **filters):
        return self.board.page(LiveCallFilters(**filters), limit, offset)

    def ids(self, **filters) -> list[str]:
        return [live.call.call_id for live in self.page(**filters).items]


# ---- The number of reads does not grow with the number of calls ----


@pytest.mark.parametrize("calls", [5, 500])
def test_the_live_view_makes_the_same_few_reads_however_many_calls_there_are(calls):
    world = _World(_item(f"c{i}") for i in range(calls))
    for i in range(calls):
        world.coverages.save(_coverage(f"c{i}"))
        world.analyses.save(f"c{i}", _tone(SentimentLabel.NEGATIVE))
        world.alert(f"c{i}")
    world.state.single_reads = world.state.batch_reads = 0
    world.alert_repository.reads = world.alert_repository.saves = 0

    page = world.page()

    assert (page.total, page.matching, len(page.items)) == (calls, calls, min(calls, 50))
    assert world.listing.reads == 1
    assert (world.coverages.batch_reads, world.coverages.single_reads) == (1, 0)
    assert (world.state.batch_reads, world.state.single_reads) == (1, 0)
    assert world.alert_repository.reads == 1
    # Reading the view writes nothing.
    assert world.alert_repository.saves == 0


def test_each_call_shows_its_tone_raised_complaints_and_standing_alerts():
    world = _World([_item("busy", executive_name="Asha", location_name="Chennai"), _item("new")])
    coverage = _coverage("busy", "Cost")
    coverage.add("Hygiene")  # listed in the coverage but not raised
    world.coverages.save(coverage)
    world.analyses.save("busy", _tone(SentimentLabel.FRUSTRATED))
    world.alert("busy", "Cost")
    world.alert("busy", "Old", cleared_at=NOW)

    busy, new = world.page().items

    assert (busy.call.executive_name, busy.call.location_name) == ("Asha", "Chennai")
    assert busy.sentiment is SentimentLabel.FRUSTRATED
    assert [c.category for c in busy.complaints] == ["Cost"]
    assert [a.subject for a in busy.alerts] == ["Cost"]
    assert (new.sentiment, new.complaints, new.alerts) == (None, (), ())


# ---- Ordering, filters, paging and the totals ----


def test_the_most_urgent_calls_come_first():
    world = _World(
        [
            _item("calm-new", NOW - 10),
            _item("calm-old", NOW - 900),
            _item(
                "escalated",
                escalation_level=EscalationLevel.HIGH,
                escalation_status=EscalationStatus.OPEN,
            ),
            _item(
                "settled",
                NOW - 500,
                escalation_level=EscalationLevel.CRITICAL,
                escalation_status=EscalationStatus.RESOLVED,
            ),
            _item("one-alert"),
            _item("two-alerts"),
        ]
    )
    world.alert("one-alert")
    world.alert("two-alerts", "Cost")
    world.alert("two-alerts", "Hygiene")

    # Most alerts, then open escalations, then the longest running. A
    # resolved escalation no longer counts.
    assert world.ids() == [
        "two-alerts",
        "one-alert",
        "escalated",
        "calm-old",
        "settled",
        "calm-new",
    ]


def test_filters_narrow_the_page_but_not_the_totals():
    world = _World(
        [
            _item("a", location_id="chennai", executive_user_id="asha"),
            _item("b", location_id="chennai", executive_user_id="ravi"),
            _item(
                "c",
                location_id="madurai",
                executive_user_id="ravi",
                escalation_level=EscalationLevel.WATCH,
                escalation_status=EscalationStatus.OPEN,
            ),
        ]
    )
    world.analyses.save("a", _tone(SentimentLabel.FRUSTRATED))
    world.analyses.save("b", _tone(SentimentLabel.POSITIVE))
    world.analyses.save("c", _tone(SentimentLabel.ESCALATING))
    world.alert("b")

    assert sorted(world.ids(location_id="chennai")) == ["a", "b"]
    assert sorted(world.ids(executive_user_id="ravi")) == ["b", "c"]
    assert world.ids(location_id="chennai", executive_user_id="ravi") == ["b"]
    assert world.ids(sentiment=SentimentLabel.FRUSTRATED) == ["a"]
    assert world.ids(alerts_only=True) == ["b"]
    assert world.ids(location_id="nowhere") == []

    page = world.page(location_id="madurai")
    assert page.matching == 1
    # The tiles count every call in progress.
    assert (page.total, page.with_alerts, page.negative_tone, page.escalated) == (3, 1, 2, 1)


def test_the_calls_are_paged():
    world = _World(_item(f"c{i:03}", NOW - i) for i in range(120))

    first, last, beyond = world.page(50, 0), world.page(50, 100), world.page(50, 150)

    assert (len(first.items), len(last.items), len(beyond.items)) == (50, 20, 0)
    assert first.matching == last.matching == beyond.matching == 120
    # Longest running first, with no call on two pages.
    assert first.items[0].call.call_id == "c119"
    seen = {live.call.call_id for offset in (0, 50, 100) for live in world.page(50, offset).items}
    assert len(seen) == 120


# ---- Many open pages cost the same as one ----


def test_requests_close_together_share_one_read():
    world = _World([_item("a")], cache_seconds=2.0)

    world.page()
    world.page(location_id="x")
    world.monotonic.now += 1.9
    world.page()
    assert world.listing.reads == 1

    world.listing.calls.append(_item("b"))
    world.monotonic.now += 0.2
    assert world.page().total == 2
    assert world.listing.reads == 2


def test_without_a_cache_every_request_reads():
    world = _World([_item("a")], cache_seconds=0.0)

    world.page()
    world.page()

    assert world.listing.reads == 2


def test_a_store_that_cannot_be_read_leaves_its_part_empty():
    world = _World([_item("a")])
    world.analyses.save("a", _tone(SentimentLabel.NEGATIVE))

    def broken(call_ids):
        raise RuntimeError("Redis is down")

    world.coverages.get_many = broken

    (live,) = world.page().items

    assert live.complaints == ()
    assert live.sentiment is SentimentLabel.NEGATIVE


def test_no_calls_in_progress_reads_nothing_else():
    world = _World()

    page = world.page()

    assert (page.items, page.total, page.matching) == ((), 0, 0)
    assert world.coverages.batch_reads == world.alert_repository.reads == 0


# ---- The background sweep keeps the alerts up to date ----


def _sweeper(world: _World, interval: float = 10.0, state=None) -> LiveAlertSweeper:
    return LiveAlertSweeper(
        world.listing, world.coverages, world.alerts, world.analyses, state or world.state, interval
    )


def _standing(world: _World, call_id: str) -> set:
    return {(a.alert_type, a.subject) for a in world.alerts.list_for_call(call_id) if a.is_open}


def test_an_alert_that_becomes_true_with_time_is_raised_without_any_analysis():
    world = _World([_item("waiting"), _item("fresh")], cache_seconds=0.0)
    world.coverages.save(_coverage("waiting", detected_at=NOW - 61))
    world.coverages.save(_coverage("fresh", detected_at=NOW - 5))
    revision = world.analyses.revision("waiting")

    assert _sweeper(world).run() == 1

    assert _standing(world, "waiting") == {(CallAlertType.UNCOVERED_CATEGORY, "Cost")}
    assert _standing(world, "fresh") == set()
    assert [live.call.call_id for live in world.page(alerts_only=True).items] == ["waiting"]
    # The executive's own screen is told.
    assert world.analyses.revision("waiting") != revision
    assert world.analyses.revision("fresh") is None


def test_the_sweep_reads_in_batches_and_writes_only_what_changed():
    world = _World(_item(f"c{i}") for i in range(500))
    for i in range(500):
        world.coverages.save(_coverage(f"c{i}", detected_at=NOW - (61 if i < 3 else 5)))
    ticks = _Clock(0.0)
    sweeper = _sweeper(world, 10.0, InMemoryLiveStateStore(clock=ticks))
    world.state.single_reads = world.state.batch_reads = 0

    assert sweeper.run() == 3

    assert (world.listing.reads, world.coverages.batch_reads, world.coverages.single_reads) == (
        1,
        1,
        0,
    )
    assert (world.alert_repository.reads, world.alert_repository.saves) == (1, 3)
    assert world.state.batch_reads == 1  # every call's audio quality at once

    # Nothing has changed by the next sweep: nothing is written.
    ticks.now += 10.0
    assert sweeper.run() == 0
    assert world.alert_repository.saves == 3


def test_the_sweep_clears_what_is_no_longer_true_and_flags_poor_audio():
    world = _World([_item("a")])
    world.coverages.save(_coverage("a", detected_at=NOW - 61))
    ticks = _Clock(0.0)
    sweeper = _sweeper(world, 10.0, InMemoryLiveStateStore(clock=ticks))
    sweeper.run()
    assert _standing(world, "a") == {(CallAlertType.UNCOVERED_CATEGORY, "Cost")}

    # Asked about meanwhile, and three stretches of speech were unintelligible.
    probed = _coverage("a")
    probed.complaints[0].status = ComplaintCoverageStatus.PROBED
    world.coverages.save(probed)
    for _ in range(3):
        world.alerts.note_audio("a", recognised=False)
    ticks.now += 10.0

    assert sweeper.run() == 1
    assert _standing(world, "a") == {(CallAlertType.POOR_AUDIO, "")}


def test_the_sweep_leaves_an_alert_it_cannot_judge():
    world = _World([_item("call-1")])
    call = Conversation(call_id="call-1")
    for index in range(4):
        call.add_utterance(
            Utterance(f"u{index}", "Hello.", SpeakerRole.CUSTOMER, ("en",), index, index + 0.5, 0.3)
        )
    world.alerts.refresh(call, None)
    judged_from_the_transcript = {(CallAlertType.POOR_AUDIO, LOW_TRANSCRIPTION_CONFIDENCE)}
    assert _standing(world, "call-1") == judged_from_the_transcript

    assert _sweeper(world).run() == 0

    assert _standing(world, "call-1") == judged_from_the_transcript


def test_only_one_instance_sweeps_in_an_interval():
    world = _World([_item("a")])
    world.coverages.save(_coverage("a", detected_at=NOW - 61))
    ticks = _Clock(0.0)
    shared = InMemoryLiveStateStore(clock=ticks)
    first, second = _sweeper(world, 10.0, shared), _sweeper(world, 10.0, shared)

    assert first.run() == 1
    assert second.run() == 0
    assert world.listing.reads == 1

    ticks.now += 10.0
    second.run()
    assert world.listing.reads == 2


# ---- Batched reads of the stores ----


class _FakeRedis:
    def __init__(self, with_mget: bool = True) -> None:
        self.store: dict[str, str] = {}
        self.mgets = 0
        self.gets = 0
        if not with_mget:
            self.mget = None

    def get(self, key):
        self.gets += 1
        return self.store.get(key)

    def set(self, key, value, ex=None, nx=False):
        self.store[key] = value
        return True

    def delete(self, key):
        self.store.pop(key, None)

    def mget(self, keys):
        self.mgets += 1
        return [self.store.get(key) for key in keys]


def _redis_coverages(client) -> RedisConversationCoverageRepository:
    settings = Settings(_env_file=None, redis_key_prefix="coverage")  # type: ignore[call-arg]
    return RedisConversationCoverageRepository(settings, client=client)


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield build_session_factory(engine)
    engine.dispose()


@pytest.mark.parametrize("store", ["memory", "redis", "redis-without-mget", "sql"])
def test_many_calls_coverage_is_read_at_once(store, session_factory):
    client = _FakeRedis(with_mget=store != "redis-without-mget")
    repository = {
        "memory": InMemoryConversationCoverageRepository,
        "redis": lambda: _redis_coverages(client),
        "redis-without-mget": lambda: _redis_coverages(client),
        "sql": lambda: PostgresConversationCoverageRepository(session_factory),
    }[store]()
    repository.save(_coverage("a", "Cost", detected_at=5.0, confidence=0.4))
    repository.save(_coverage("b", "Hygiene"))

    found = repository.get_many(["a", "missing", "b"])

    assert set(found) == {"a", "b"}
    (complaint,) = found["a"].complaints
    # What the alerts are judged from survives the store.
    assert (complaint.category, complaint.status, complaint.confidence, complaint.detected_at) == (
        "Cost",
        ComplaintCoverageStatus.DETECTED,
        0.4,
        5.0,
    )
    assert repository.get_many([]) == {}
    if store == "redis":
        assert (client.mgets, client.gets) == (1, 0)


def test_redis_coverage_written_before_confidence_was_stored_still_reads():
    client = _FakeRedis()
    client.store["coverage:old"] = json.dumps(
        {"call_id": "old", "complaints": [{"category": "Cost", "status": "detected"}]}
    )
    client.store["coverage:broken"] = "{not json"

    found = _redis_coverages(client).get_many(["old", "broken"])

    # One unreadable entry does not hide the other calls.
    assert set(found) == {"old"}
    assert found["old"].complaints[0].confidence is None


def test_live_state_and_live_analyses_are_read_at_once():
    client = _FakeRedis()
    state = RedisLiveStateStore(client)
    analyses = LiveAnalysisStore(state)
    analyses.save("a", _tone(SentimentLabel.POSITIVE))
    analyses.save("b", _tone(SentimentLabel.ESCALATING))
    state.set_json("live_analysis:odd", {"v": 99})
    client.gets = 0

    assert state.get_many_json(["nothing", "live_analysis:odd"]) == [None, {"v": 99}]
    found = analyses.load_many(["a", "missing", "odd", "b"])

    assert {call_id: s.sentiment.label for call_id, s in found.items()} == {
        "a": SentimentLabel.POSITIVE,
        "b": SentimentLabel.ESCALATING,
    }
    assert (client.mgets, client.gets) == (2, 0)
    assert InMemoryLiveStateStore().get_many_json([]) == []


def test_the_database_lists_only_the_calls_in_progress_with_their_line_counts(session_factory):
    conversations = PostgresConversationRepository(session_factory)
    for call_id, lines, completed in (("busy", 3, False), ("silent", 0, False), ("over", 2, True)):
        call = Conversation(call_id=call_id, start_time=100.0)
        for index in range(lines):
            call.add_utterance(
                Utterance(
                    f"{call_id}-{index}", "Hello.", SpeakerRole.CUSTOMER, ("en",), index, index + 0.5
                )
            )
        if completed:
            call.complete(160.0)
        conversations.add(call)
    listing = PostgresCallListingQuery(session_factory)

    active = {item.call_id: item for item in listing.active_calls(50)}

    assert {call_id: item.utterance_count for call_id, item in active.items()} == {
        "busy": 3,
        "silent": 0,
    }
    assert all(item.status is ConversationStatus.ACTIVE for item in active.values())
    assert len(listing.active_calls(1)) == 1


# ---- The endpoint ----


class _NoComplaints(ComplaintDetectionProvider):
    def detect(self, conversation, learning_context=()):
        return []


class _Calm(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEUTRAL, 0.7, "Calm.")


class _NoQuestions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


def test_the_endpoint_pages_and_filters_the_calls_in_progress():
    settings = Settings(_env_file=None, live_calls_cache_seconds=0.0)  # type: ignore[call-arg]
    services = build_api_services(_NoComplaints(), _Calm(), _NoQuestions(), settings)
    client = TestClient(create_app(services))

    def sign_in(user_id: str, role: UserRole) -> dict[str, str]:
        user = User(user_id, f"{user_id}@example.com", "hash", role, True, NOW)
        services.user_repository.save(user)
        return {"Authorization": f"Bearer {create_access_token(user)}"}

    asha, ravi = sign_in("asha", UserRole.ICR), sign_in("ravi", UserRole.ICR)
    supervisor = sign_in("sup", UserRole.SUPERVISOR)
    for index in range(3):
        client.post("/api/v1/calls", json={"call_id": f"a{index}", "start_time": None}, headers=asha)
    client.post("/api/v1/calls", json={"call_id": "r0", "start_time": None}, headers=ravi)

    def view(**params) -> dict:
        response = client.get("/api/v1/live-calls", params=params, headers=supervisor)
        assert response.status_code == 200
        return response.json()

    everything = view()
    assert (everything["total"], everything["matching"], everything["limit"]) == (4, 4, 50)
    assert (everything["with_alerts"], everything["negative_tone"], everything["escalated"]) == (
        0,
        0,
        0,
    )

    page = view(limit=2, offset=2)
    assert (len(page["items"]), page["offset"], page["matching"]) == (2, 2, 4)

    only_ravi = view(executive_user_id="ravi")
    assert [call["call_id"] for call in only_ravi["items"]] == ["r0"]
    assert (only_ravi["matching"], only_ravi["total"]) == (1, 4)
    assert view(alerts_only=True)["items"] == []
    assert view(sentiment="FRUSTRATED")["matching"] == 0

    bad = client.get("/api/v1/live-calls", params={"limit": 1000}, headers=supervisor)
    assert bad.status_code == 422
    assert client.get("/api/v1/live-calls", headers=asha).status_code == 403
