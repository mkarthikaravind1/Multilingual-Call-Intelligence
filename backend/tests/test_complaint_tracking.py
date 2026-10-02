"""Complaint lifecycle and emerging complaints: the domain rules, the
services, their wiring into the call workflow, and the API through the real
composition root."""

import time
from concurrent.futures import Executor, Future

import pytest
from fastapi.testclient import TestClient

from app.ai.complaint.provider import ComplaintDetectionProvider, ComplaintDetectionResult
from app.ai.emerging_complaint.provider import (
    EmergingComplaintDiscoveryProvider,
    EmergingComplaintDiscoveryRequest,
)
from app.ai.emerging_complaint.rule_based_provider import (
    RuleBasedEmergingComplaintDiscoveryProvider,
)
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
)
from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.core.config import Settings
from app.crm.provider import CustomerDirectory
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.complaint_lifecycle import (
    ComplaintLifecycleEvent,
    ComplaintLifecycleRecord,
    ComplaintLifecycleStatus,
)
from app.domain.complaint_lifecycle_repository import InMemoryComplaintLifecycleRepository
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.customer import CustomerProfile
from app.domain.emerging_complaint_candidate import (
    EmergingComplaintCandidate,
    EmergingComplaintReviewError,
    EmergingComplaintReviewStatus,
)
from app.domain.user import User, UserRole
from app.security.jwt import create_access_token
from app.services.complaint_lifecycle_service import (
    CALL_ENDED_NOTE,
    ComplaintActionError,
    ComplaintLifecycleService,
)
from app.services.emerging_complaint_repository import InMemoryEmergingComplaintRepository
from app.services.emerging_complaint_service import (
    MAX_EVIDENCE_PER_CANDIDATE,
    EmergingComplaintNotFoundError,
    EmergingComplaintService,
)

S = ComplaintLifecycleStatus


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def coverage(call_id: str, **statuses: ComplaintCoverageStatus) -> ConversationCoverage:
    steps = {
        ComplaintCoverageStatus.DETECTED: ("detect",),
        ComplaintCoverageStatus.PROBED: ("detect", "probe"),
        ComplaintCoverageStatus.COVERED: ("detect", "probe", "cover"),
        ComplaintCoverageStatus.RESOLVED: ("detect", "probe", "cover", "resolve"),
    }
    result = ConversationCoverage(call_id=call_id)
    for key, status in statuses.items():
        complaint = result.add(key.replace("_", " "))
        for step in steps[status]:
            getattr(complaint, step)()
    return result


def lifecycle(clock: Clock | None = None):
    repository = InMemoryComplaintLifecycleRepository()
    return ComplaintLifecycleService(repository, clock=clock or Clock()), repository


# ---- Domain ----


def record(status: ComplaintLifecycleStatus) -> ComplaintLifecycleRecord:
    return ComplaintLifecycleRecord("c:Cost", "c", "Cost", status, 1.0, 1.0)


@pytest.mark.parametrize(
    "status, actions",
    [
        (S.DETECTED, (S.RESOLVED, S.UNRESOLVED)),
        (S.PROBED, (S.RESOLVED, S.UNRESOLVED)),
        (S.COVERED, (S.RESOLVED, S.UNRESOLVED)),
        (S.UNRESOLVED, (S.RESOLVED, S.FOLLOW_UP)),
        (S.RESOLVED, (S.FOLLOW_UP,)),
        (S.FOLLOW_UP, (S.RESOLVED,)),
    ],
)
def test_people_can_close_a_complaint_wherever_the_call_left_it(status, actions):
    assert record(status).allowed_actions() == actions


def test_only_resolved_is_closed():
    assert not record(S.RESOLVED).is_open
    assert all(record(s).is_open for s in S if s is not S.RESOLVED)


def test_event_requires_an_actor():
    with pytest.raises(ValueError):
        ComplaintLifecycleEvent("c:Cost", S.DETECTED, 1.0, " ")


# ---- Lifecycle service ----


def test_sync_creates_and_advances_records_with_system_events():
    service, _ = lifecycle()
    service.sync_from_coverage(coverage("c", Cost=ComplaintCoverageStatus.DETECTED), at=10.0)
    service.sync_from_coverage(
        coverage("c", Cost=ComplaintCoverageStatus.COVERED, Hygiene=ComplaintCoverageStatus.DETECTED),
        at=20.0,
    )

    views = {v.record.category: v for v in service.list_for_call("c")}
    assert views["Cost"].record.status is S.COVERED
    assert [e.status for e in views["Cost"].events] == [S.DETECTED, S.PROBED, S.COVERED]
    assert {e.actor for e in views["Cost"].events} == {"system"}
    assert views["Hygiene"].record.status is S.DETECTED
    assert views["Hygiene"].record.first_detected_at == 20.0


def test_sync_never_undoes_a_decision_made_by_a_person():
    service, _ = lifecycle()
    service.sync_from_coverage(coverage("c", Cost=ComplaintCoverageStatus.DETECTED), at=1.0)
    service.apply_action("c:Cost", S.RESOLVED, "agent@example.com", "Refunded.")

    service.sync_from_coverage(coverage("c", Cost=ComplaintCoverageStatus.COVERED), at=2.0)

    assert service.get("c:Cost").status is S.RESOLVED


def test_closing_a_call_flags_open_complaints_for_follow_up_once():
    clock = Clock()
    service, _ = lifecycle(clock)
    service.sync_from_coverage(
        coverage("c", Cost=ComplaintCoverageStatus.PROBED, Hygiene=ComplaintCoverageStatus.RESOLVED),
        at=5.0,
    )

    service.close_call("c", customer_id="cust-1")
    service.close_call("c", customer_id="cust-2")

    cost = service.get_view("c:Cost")
    hygiene = service.get("c:Hygiene")
    assert cost.record.follow_up_required and cost.record.customer_id == "cust-1"
    assert cost.events[-1].note == CALL_ENDED_NOTE
    assert [e.note for e in cost.events].count(CALL_ENDED_NOTE) == 1
    assert not hygiene.follow_up_required and hygiene.customer_id == "cust-1"


def test_people_resolve_and_schedule_follow_ups_with_a_history():
    clock = Clock()
    service, _ = lifecycle(clock)
    service.sync_from_coverage(coverage("c", Cost=ComplaintCoverageStatus.DETECTED), at=1.0)
    service.close_call("c")

    clock.now = 2000.0
    unresolved = service.apply_action("c:Cost", S.UNRESOLVED, "a@example.com", "  ")
    follow_up = service.apply_action("c:Cost", S.FOLLOW_UP, "a@example.com", "Call back Monday.")
    assert follow_up.record.follow_up_required
    resolved = service.apply_action("c:Cost", S.RESOLVED, "sup@example.com", "Part replaced.")

    assert unresolved.events[-1].note is None
    assert resolved.record.status is S.RESOLVED and not resolved.record.follow_up_required
    assert [(e.status, e.actor) for e in resolved.events[-3:]] == [
        (S.UNRESOLVED, "a@example.com"),
        (S.FOLLOW_UP, "a@example.com"),
        (S.RESOLVED, "sup@example.com"),
    ]
    assert resolved.events[-1].at == 2000.0


def test_actions_are_limited_to_what_the_complaint_allows():
    service, _ = lifecycle()
    service.sync_from_coverage(coverage("c", Cost=ComplaintCoverageStatus.DETECTED), at=1.0)

    with pytest.raises(ComplaintActionError):
        service.apply_action("c:Cost", S.PROBED, "a@example.com")  # driven by the call
    with pytest.raises(ComplaintActionError):
        service.apply_action("c:Cost", S.FOLLOW_UP, "a@example.com")  # not from detected


def test_queue_puts_follow_ups_first_then_oldest():
    service, repository = lifecycle()
    for call_id, detected, follow_up, status in (
        ("new", 30.0, False, S.DETECTED),
        ("old", 10.0, False, S.COVERED),
        ("flagged", 20.0, True, S.UNRESOLVED),
        ("done", 5.0, False, S.RESOLVED),
    ):
        repository.save(
            ComplaintLifecycleRecord(
                f"{call_id}:Cost", call_id, "Cost", status, detected, detected, follow_up
            )
        )

    assert [v.record.call_id for v in service.list_queue("open")] == ["flagged", "old", "new"]
    assert [v.record.call_id for v in service.list_queue("resolved")] == ["done"]
    assert [v.record.call_id for v in service.list_queue("all")][0] == "new"
    with pytest.raises(ValueError):
        service.list_queue("everything")


def test_customer_history_excludes_the_current_call_and_attach_backfills():
    service, _ = lifecycle()
    service.sync_from_coverage(coverage("old", Cost=ComplaintCoverageStatus.DETECTED), at=1.0)
    service.close_call("old", customer_id="cust-1")
    service.sync_from_coverage(coverage("now", Hygiene=ComplaintCoverageStatus.DETECTED), at=2.0)

    service.attach_customer("now", "cust-1")

    assert service.get("now:Hygiene").customer_id == "cust-1"
    assert [v.record.call_id for v in service.customer_history("cust-1", "now")] == ["old"]


# ---- Emerging complaints ----


def candidate(**overrides) -> EmergingComplaintCandidate:
    values = dict(
        candidate_id="emerging-1",
        proposed_name="Ac Smell",
        description="Smell from the AC.",
        evidence=("the ac smells bad",),
        occurrence_count=2,
        confidence=0.5,
        call_ids=("a", "b"),
    )
    values.update(overrides)
    return EmergingComplaintCandidate(**values)


def test_review_accepts_rejects_and_reopens():
    stored = candidate().first_stored(10.0)

    accepted = stored.review(EmergingComplaintReviewStatus.ACCEPTED, "sup@example.com", 20.0, " Real ")
    reopened = accepted.review(EmergingComplaintReviewStatus.PENDING_REVIEW, "sup@example.com", 30.0)

    assert (accepted.reviewed_by, accepted.reviewed_at, accepted.review_note) == (
        "sup@example.com",
        20.0,
        "Real",
    )
    assert reopened.status is EmergingComplaintReviewStatus.PENDING_REVIEW
    assert reopened.reviewed_by is None
    with pytest.raises(EmergingComplaintReviewError):
        stored.review(EmergingComplaintReviewStatus.PENDING_REVIEW, "sup@example.com", 30.0)


def test_refresh_keeps_the_review_decision():
    rejected = candidate().first_stored(10.0).review(
        EmergingComplaintReviewStatus.REJECTED, "sup@example.com", 11.0
    )

    refreshed = rejected.refreshed_from(
        candidate(occurrence_count=5, call_ids=("a", "b", "c")), 50.0
    )

    assert refreshed.status is EmergingComplaintReviewStatus.REJECTED
    assert (refreshed.occurrence_count, refreshed.call_ids) == (5, ("a", "b", "c"))
    assert (refreshed.first_seen_at, refreshed.last_seen_at) == (10.0, 50.0)


class InlineExecutor(Executor):
    """Collects submitted work so a test decides when it runs."""

    def __init__(self) -> None:
        self.queued = []

    def submit(self, fn, *args, **kwargs):
        self.queued.append((fn, args, kwargs))
        return Future()

    def run_all(self) -> None:
        queued, self.queued = self.queued, []
        for fn, args, kwargs in queued:
            fn(*args, **kwargs)


class FakeProvider(EmergingComplaintDiscoveryProvider):
    def __init__(self, *results: EmergingComplaintCandidate) -> None:
        self.results = results
        self.requests: list[EmergingComplaintDiscoveryRequest] = []

    def discover(self, request):
        self.requests.append(request)
        return self.results


def _api(provider: EmergingComplaintDiscoveryProvider | None = None, directory=None, **settings):
    services = build_api_services(
        _Complaints(),
        _Sentiment(),
        _Questions(),
        Settings(_env_file=None, emerging_complaint_auto_discovery=False, **settings),  # type: ignore[call-arg]
        emerging_complaint_provider=provider,
        customer_directory=directory,
    )
    return create_app(services)


def _completed_call(client: TestClient, call_id: str, *lines: str, caller: str | None = None) -> None:
    body = {"call_id": call_id}
    if caller:
        body["caller_number"] = caller
    assert client.post("/api/v1/calls", json=body).status_code == 201
    for index, line in enumerate(lines):
        _say(client, call_id, index, line)
    assert client.post(f"/api/v1/calls/{call_id}/complete", json={"end_time": 99.0}).status_code == 200


def test_discovery_needs_two_completed_calls_and_keeps_rejections():
    app = _api(RuleBasedEmergingComplaintDiscoveryProvider())
    icr = _client(app, UserRole.ICR)
    service: EmergingComplaintService = app.state.services.emerging_complaint_service

    _completed_call(icr, "a", "The AC smells like smoke")
    skipped = service.discover()
    assert skipped.calls_scanned == 1 and skipped.skipped_reason

    _completed_call(icr, "b", "the AC smells like smoke!")
    icr.post("/api/v1/calls", json={"call_id": "active"})
    _say(icr, "active", 0, "The AC smells like smoke")  # active calls are not read

    run = service.discover()
    (found,) = service.list_candidates()
    assert (run.calls_scanned, run.new_candidates) == (2, 1)
    assert set(found.call_ids) == {"a", "b"}

    service.review(found.candidate_id, EmergingComplaintReviewStatus.REJECTED, "sup@example.com")
    _completed_call(icr, "c", "The AC smells like smoke.")
    rerun = service.discover()

    (again,) = service.list_candidates()
    assert rerun.new_candidates == 0
    assert again.status is EmergingComplaintReviewStatus.REJECTED
    assert set(again.call_ids) == {"a", "b", "c"}


def test_background_discovery_is_coalesced():
    provider = FakeProvider()
    executor = InlineExecutor()
    app = _api(provider)
    services = app.state.services
    service = EmergingComplaintService(
        InMemoryEmergingComplaintRepository(),
        provider,
        services.call_service,
        InMemoryCoverage(),
        executor=executor,
    )
    icr = _client(app, UserRole.ICR)
    _completed_call(icr, "a", "one two")
    _completed_call(icr, "b", "three four")

    assert service.request_discovery() is True
    assert service.request_discovery() is False
    executor.run_all()
    assert len(provider.requests) == 1
    assert service.request_discovery() is True


def _background_service(app, provider, **kwargs):
    return EmergingComplaintService(
        InMemoryEmergingComplaintRepository(),
        provider,
        app.state.services.call_service,
        InMemoryCoverage(),
        **kwargs,
    )


def test_background_discovery_skips_unchanged_calls_but_manual_runs_do_not():
    provider = FakeProvider()
    executor = InlineExecutor()
    app = _api(provider)
    service = _background_service(app, provider, executor=executor)
    icr = _client(app, UserRole.ICR)
    _completed_call(icr, "a", "one two")
    _completed_call(icr, "b", "three four")

    service.request_discovery()
    executor.run_all()
    service.request_discovery()  # e.g. a post-call repair of an old call
    executor.run_all()
    assert len(provider.requests) == 1

    service.discover()  # a supervisor asked explicitly
    assert len(provider.requests) == 2

    _completed_call(icr, "c", "five six")
    service.request_discovery()
    executor.run_all()
    assert len(provider.requests) == 3
    assert len(provider.requests[-1].call_records) == 3


def test_background_discovery_waits_for_the_minimum_interval():
    provider = FakeProvider()
    executor = InlineExecutor()
    now = [1000.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    app = _api(provider)
    service = _background_service(
        app,
        provider,
        executor=executor,
        clock=lambda: now[0],
        sleep=sleep,
        min_interval_seconds=300,
    )
    icr = _client(app, UserRole.ICR)
    _completed_call(icr, "a", "one two")
    _completed_call(icr, "b", "three four")

    service.request_discovery()
    executor.run_all()
    assert slept == [] and len(provider.requests) == 1

    now[0] += 100
    _completed_call(icr, "c", "five six")
    assert service.request_discovery() is True
    assert service.request_discovery() is False  # coalesced while waiting
    executor.run_all()

    assert slept == [200.0]
    assert len(provider.requests) == 2


def test_background_discovery_runs_on_one_instance_at_a_time():
    from app.services.live_state_store import InMemoryLiveStateStore

    provider = FakeProvider()
    executor = InlineExecutor()
    store = InMemoryLiveStateStore()
    app = _api(provider)
    service = _background_service(app, provider, executor=executor, store=store)
    icr = _client(app, UserRole.ICR)
    _completed_call(icr, "a", "one two")
    _completed_call(icr, "b", "three four")

    token = store.acquire_lock("emerging_complaints:discovery", 60)  # another instance
    service.request_discovery()
    executor.run_all()
    assert provider.requests == []

    store.release_lock("emerging_complaints:discovery", token)
    service.request_discovery()
    executor.run_all()
    assert len(provider.requests) == 1


def test_instances_sharing_live_state_do_not_repeat_a_scan():
    from app.services.live_state_store import InMemoryLiveStateStore

    provider = FakeProvider()
    executor = InlineExecutor()
    store = InMemoryLiveStateStore()
    app = _api(provider)
    first = _background_service(app, provider, executor=executor, store=store)
    second = _background_service(app, provider, executor=executor, store=store)
    icr = _client(app, UserRole.ICR)
    _completed_call(icr, "a", "one two")
    _completed_call(icr, "b", "three four")

    first.request_discovery()
    second.request_discovery()
    executor.run_all()

    assert len(provider.requests) == 1
    assert second.last_run is not None


def test_failed_background_discovery_is_retried_next_time():
    class Flaky(FakeProvider):
        def discover(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                raise RuntimeError("LLM unavailable")
            return ()

    provider = Flaky()
    executor = InlineExecutor()
    app = _api(provider)
    service = _background_service(app, provider, executor=executor)
    icr = _client(app, UserRole.ICR)
    _completed_call(icr, "a", "one two")
    _completed_call(icr, "b", "three four")

    service.request_discovery()
    executor.run_all()
    service.request_discovery()
    executor.run_all()

    assert len(provider.requests) == 2


def test_evidence_is_trimmed_when_stored():
    many = tuple(f"quote {i}" for i in range(MAX_EVIDENCE_PER_CANDIDATE + 5))
    app = _api(FakeProvider(candidate(evidence=many)))
    icr = _client(app, UserRole.ICR)
    _completed_call(icr, "a", "x y")
    _completed_call(icr, "b", "x y")
    service = app.state.services.emerging_complaint_service

    service.discover()

    assert len(service.list_candidates()[0].evidence) == MAX_EVIDENCE_PER_CANDIDATE
    with pytest.raises(EmergingComplaintNotFoundError):
        service.review("missing", EmergingComplaintReviewStatus.ACCEPTED, "sup@example.com")


class InMemoryCoverage:
    def get(self, call_id):
        return None


# ---- Workflow + API ----


class _Complaints(ComplaintDetectionProvider):
    def detect(self, conversation, learning_context=()):
        return [ComplaintDetectionResult("Turnaround Time", 0.9, "The car was late.")]


class _Sentiment(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEUTRAL, 0.6, "Calm.")


class _Questions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


class _Directory(CustomerDirectory):
    CUSTOMER = CustomerProfile("cust-1", "Priya", "+919876543210")

    def find_by_phone(self, phone_number):
        return self.CUSTOMER if phone_number == self.CUSTOMER.phone_number else None

    def get_customer(self, customer_id):
        return self.CUSTOMER if customer_id == "cust-1" else None

    def list_vehicles(self, customer_id):
        return ()

    def list_service_history(self, vehicle_id):
        return ()


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


def test_calls_feed_the_lifecycle_and_completion_flags_follow_up():
    app = _api(directory=_Directory())
    icr = _client(app, UserRole.ICR)

    icr.post("/api/v1/calls", json={"call_id": "live", "caller_number": "9876543210"})
    _say(icr, "live", 0, "My car is late again.")
    (open_item,) = icr.get("/api/v1/complaints").json()
    assert open_item["complaint_id"] == "live:Turnaround Time"
    assert open_item["status"] == "detected" and not open_item["follow_up_required"]

    icr.post("/api/v1/calls/live/complete", json={"end_time": 50.0})

    body = icr.get("/api/v1/calls/live/complaints").json()
    (complaint,) = body["complaints"]
    assert body["customer_id"] == "cust-1"
    assert complaint["customer_id"] == "cust-1" and complaint["follow_up_required"]
    assert complaint["allowed_actions"] == ["resolved", "unresolved"]
    assert complaint["events"][-1]["note"] == CALL_ENDED_NOTE


def test_complaints_are_worked_through_the_api_and_show_in_customer_history():
    app = _api(directory=_Directory())
    icr = _client(app, UserRole.ICR)
    _completed_call(icr, "first", "Still waiting for my car.", caller="9876543210")
    _completed_call(icr, "second", "It is late again.", caller="9876543210")
    complaint_id = "first:Turnaround Time"

    bad = icr.post(f"/api/v1/complaints/{complaint_id}/status", json={"status": "follow_up"})
    assert bad.status_code == 409
    assert icr.post(f"/api/v1/complaints/{complaint_id}/status", json={"status": "probed"}).status_code == 422
    resolved = icr.post(
        f"/api/v1/complaints/{complaint_id}/status",
        json={"status": "resolved", "note": "Delivered today."},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved" and not resolved.json()["is_open"]
    assert resolved.json()["events"][-1]["actor"] == "icr@example.com"

    history = icr.get("/api/v1/calls/second/complaints").json()["customer_history"]
    assert [c["complaint_id"] for c in history] == [complaint_id]
    assert [c["call_id"] for c in icr.get("/api/v1/complaints?state=resolved").json()] == ["first"]
    assert icr.get("/api/v1/complaints/missing:Cost").status_code == 404
    assert icr.get("/api/v1/calls/nope/complaints").status_code == 404


def test_emerging_complaints_api_is_reviewed_by_supervisors():
    app = _api(RuleBasedEmergingComplaintDiscoveryProvider())
    icr = _client(app, UserRole.ICR)
    supervisor = _client(app, UserRole.SUPERVISOR)
    _completed_call(icr, "a", "Wiper makes a squeaking noise")
    _completed_call(icr, "b", "wiper makes a squeaking noise")

    assert icr.get("/api/v1/emerging-complaints").json() == {"candidates": [], "last_run": None}
    assert icr.post("/api/v1/emerging-complaints/discover").status_code == 403
    run = supervisor.post("/api/v1/emerging-complaints/discover").json()
    assert run["new_candidates"] == 1

    listing = icr.get("/api/v1/emerging-complaints").json()
    (item,) = listing["candidates"]
    assert listing["last_run"]["calls_scanned"] == 2
    assert item["status"] == "pending_review" and sorted(item["call_ids"]) == ["a", "b"]

    url = f"/api/v1/emerging-complaints/{item['candidate_id']}/review"
    assert icr.post(url, json={"decision": "accepted"}).status_code == 403
    accepted = supervisor.post(url, json={"decision": "accepted", "note": "Real issue"})
    assert accepted.json()["reviewed_by"] == "supervisor@example.com"
    assert supervisor.post(url, json={"decision": "accepted"}).status_code == 409
    assert supervisor.post(
        "/api/v1/emerging-complaints/missing/review", json={"decision": "rejected"}
    ).status_code == 404
    assert icr.get("/api/v1/emerging-complaints?status=pending_review").json()["candidates"] == []


def test_completion_requests_background_discovery_when_enabled():
    services = build_api_services(
        _Complaints(),
        _Sentiment(),
        _Questions(),
        Settings(_env_file=None, emerging_complaint_auto_discovery=True),  # type: ignore[call-arg]
        emerging_complaint_provider=FakeProvider(),
    )
    requested = []
    services.emerging_complaint_service.request_discovery = lambda: requested.append(True)
    icr = _client(create_app(services), UserRole.ICR)

    _completed_call(icr, "a", "Hello there")

    assert requested == [True]
