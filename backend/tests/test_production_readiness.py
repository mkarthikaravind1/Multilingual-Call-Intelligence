"""Production readiness: shared live state, the telephony stream token,
post-call repair, user provisioning, monitoring and configuration checks."""

import logging
import threading
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentLabel, SentimentResult
from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.core.config import Settings
from app.core.production_checks import (
    UnsafeConfigurationError,
    check_configuration,
    configuration_problems,
)
from app.domain.user import User, UserRole
from app.domain.user_repository import InMemoryUserRepository
from app.domain.utterance import SpeakerRole
from app.observability.metrics import Counter, Gauge, Histogram, MetricsRegistry
from app.security.jwt import create_access_token
from app.security.stream_token import create_stream_token, is_valid_stream_token
from app.services.auth_service import AuthService, EmailAlreadyRegisteredError
from app.services.background_jobs import BackgroundJobRunner, PeriodicJob
from app.services.call_service import CallService
from app.services.conversation_service import ConversationService
from app.services.in_memory_conversation_repository import InMemoryConversationRepository
from app.services.live_state_store import InMemoryLiveStateStore, RedisLiveStateStore
from app.services.post_call_repair_service import (
    NO_SUMMARY_ERROR,
    CallNotRepairableError,
    PostCallRepairService,
)
from app.services.post_call_summary_repository import InMemoryPostCallSummaryRepository
from app.services.speaker_session_registry import SpeakerSessionRegistry
from app.services.telephony_call_mapping_repository import InMemoryTelephonyCallMappingRepository
from app.services.telephony_call_service import TelephonyCallService
from app.services.user_management_service import UserManagementError, UserManagementService
from app.telephony.plivo.provider import PlivoTelephonyProvider
from app.telephony.provider import InboundCallEvent


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


# ---- Live state store ----


class FakeRedis:
    """Enough of redis-py for RedisLiveStateStore (no expiry)."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    def delete(self, key):
        self.data.pop(key, None)

    def eval(self, script, numkeys, key, token):
        if self.data.get(key) == token:
            del self.data[key]
            return 1
        return 0

    def ping(self):
        return True


@pytest.fixture(params=["memory", "redis"])
def store(request):
    if request.param == "memory":
        return InMemoryLiveStateStore()
    return RedisLiveStateStore(FakeRedis(), "test")


def test_store_round_trips_json_and_deletes(store):
    store.set_json("k", {"a": [1, 2]})
    assert store.get_json("k") == {"a": [1, 2]}
    store.delete("k")
    assert store.get_json("k") is None


def test_locks_are_exclusive_and_released_only_by_their_holder(store):
    token = store.acquire_lock("job", 60)
    assert token is not None
    assert store.acquire_lock("job", 60) is None
    store.release_lock("job", "someone-else")
    assert store.acquire_lock("job", 60) is None
    store.release_lock("job", token)
    assert store.acquire_lock("job", 60) is not None


def test_in_memory_values_and_locks_expire():
    clock = Clock()
    store = InMemoryLiveStateStore(clock)
    store.set_json("k", 1, ttl_seconds=10)
    store.acquire_lock("job", 10)
    clock.now += 11
    assert store.get_json("k") is None
    assert store.acquire_lock("job", 10) is not None


def test_redis_store_prefixes_keys():
    redis = FakeRedis()
    RedisLiveStateStore(redis, "prod").set_json("stream:c1", True, ttl_seconds=5)
    assert list(redis.data) == ["prod:stream:c1"]


# ---- Shared live state across instances ----


def _telephony(store, call_service=None, timeout=2.0):
    call_service = call_service or CallService(ConversationService(InMemoryConversationRepository()))
    return TelephonyCallService(
        call_service,
        InMemoryTelephonyCallMappingRepository(),
        stream_drain_timeout_seconds=timeout,
        live_state=store,
    )


def test_status_webhook_on_another_instance_waits_for_the_stream():
    store = InMemoryLiveStateStore()
    calls = CallService(ConversationService(InMemoryConversationRepository()))
    streaming = _telephony(store, calls)
    webhook = _telephony(store, calls)
    webhook._mapping_repository = streaming._mapping_repository  # shared, as with Redis
    call_id = streaming.start_call_from_provider(
        "plivo", InboundCallEvent(provider_call_id="uuid-1", from_number="+91123", to_number="+91456")
    )
    streaming.stream_opened(call_id)

    from app.telephony.provider import CallProviderStatus, CallStatusEvent

    event = CallStatusEvent(provider_call_id="uuid-1", status=CallProviderStatus.COMPLETED)
    assert webhook.call_awaiting_stream_drain(event) == call_id

    threading.Timer(0.3, streaming.stream_drained, args=(call_id,)).start()
    started = time.monotonic()
    assert webhook.wait_for_stream_drain(call_id) is True
    assert 0.2 < time.monotonic() - started < 2.0
    assert webhook.call_awaiting_stream_drain(event) is None


def test_waiting_for_a_remote_stream_times_out():
    store = InMemoryLiveStateStore()
    store.set_json("stream:c1", True)
    assert _telephony(store, timeout=0.3).wait_for_stream_drain("c1") is False


def test_speaker_roles_survive_a_move_to_another_instance():
    store = InMemoryLiveStateStore()
    SpeakerSessionRegistry(store).get_or_create("c1").assign("SPEAKER_00", SpeakerRole.ICR)

    session = SpeakerSessionRegistry(store).get_or_create("c1")

    assert session.role_for("SPEAKER_00") is SpeakerRole.ICR
    assert SpeakerSessionRegistry(store).get("other") is None


# ---- Telephony stream token ----


def test_stream_token_is_bound_to_its_call_and_purpose():
    token = create_stream_token("call-1")

    assert is_valid_stream_token(token, "call-1")
    assert not is_valid_stream_token(token, "call-2")
    assert not is_valid_stream_token(None, "call-1")
    assert not is_valid_stream_token(token + "x", "call-1")


def test_a_user_access_token_is_not_a_stream_token():
    user = User("u1", "a@example.com", "hash", UserRole.ADMIN, True, 1.0)
    assert not is_valid_stream_token(create_access_token(user), "u1")


def test_stream_url_is_xml_escaped():
    provider = PlivoTelephonyProvider(
        Settings(_env_file=None, plivo_auth_token="t")  # type: ignore[call-arg]
    )
    content = provider.build_stream_response("wss://x/stream?token=a&b=c").content
    assert "token=a&amp;b=c" in content


# ---- Through the API ----


class _Complaints(ComplaintDetectionProvider):
    def detect(self, conversation, learning_context=()):
        return []


class _Sentiment(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEUTRAL, 0.6, "Calm.")


class _Questions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


def _services(**settings):
    values = {"emerging_complaint_auto_discovery": False, "post_call_repair_interval_seconds": 0}
    values.update(settings)
    return build_api_services(
        _Complaints(), _Sentiment(), _Questions(), Settings(_env_file=None, **values)  # type: ignore[call-arg]
    )


def _user(services, role: UserRole, email: str | None = None) -> User:
    return services.user_management_service.create_user(
        email or f"{role.value.lower()}@example.com", "password-123", role
    )


def _client(app, user: User | None = None) -> TestClient:
    headers = {} if user is None else {"Authorization": f"Bearer {create_access_token(user)}"}
    return TestClient(app, headers=headers)


def test_telephony_stream_without_a_valid_token_is_refused():
    services = _services()
    services.call_service.start_call("c1")
    client = _client(create_app(services))

    for path in (
        "/api/v1/calls/c1/telephony-stream",
        f"/api/v1/calls/c1/telephony-stream?token={create_stream_token('other')}",
    ):
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect(path) as ws:
                ws.receive_text()
        assert closed.value.code == 4401


# ---- Post-call repair ----


class Processor:
    def __init__(self, summaries, results) -> None:
        self.summaries = summaries
        self.results = list(results)
        self.calls: list[str] = []

    def __call__(self, call_id):
        self.calls.append(call_id)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _completed_calls(*call_ids: str) -> CallService:
    from app.domain.utterance import Utterance

    calls = CallService(ConversationService(InMemoryConversationRepository()))
    for call_id in call_ids:
        calls.start_call(call_id)
        calls.add_utterance(
            call_id,
            Utterance(
                utterance_id=f"{call_id}-u",
                transcript="Hello",
                speaker_role=SpeakerRole.CUSTOMER,
                languages=("en",),
                start_time=0.0,
                end_time=1.0,
            ),
        )
        calls.end_call(call_id, 5.0)
    return calls


def _repair(calls, results, clock, **kwargs):
    summaries = InMemoryPostCallSummaryRepository()
    process = Processor(summaries, results)
    service = PostCallRepairService(
        calls,
        process,
        summaries,
        InMemoryLiveStateStore(),
        min_age_seconds=100,
        max_attempts=kwargs.get("max_attempts", 3),
        clock=clock,
    )
    return service, process


def test_repair_waits_then_backs_off_and_finally_gives_up():
    clock = Clock()
    calls = _completed_calls("c1")
    service, process = _repair(calls, [None, RuntimeError("LLM down"), None], clock)

    assert service.run().pending == 1 and process.calls == []  # first noticed now
    clock.now += 100
    assert service.run().failed == 1
    clock.now += 100  # backoff after 1 attempt: 100s
    run = service.run()
    assert run.failed == 1
    (pending,) = service.pending()
    assert pending.attempts == 2 and pending.last_error == "RuntimeError: LLM down"
    clock.now += 150  # backoff after 2 attempts: 200s - not due yet
    assert service.run().failed == 0
    clock.now += 50
    service.run()
    assert service.pending()[0].gave_up
    clock.now += 10_000
    assert service.run().gave_up == 1 and len(process.calls) == 3
    assert service.last_run.gave_up == 1


def test_repair_clears_state_once_repaired_and_manual_retry_ignores_limits():
    clock = Clock()
    calls = _completed_calls("c1")
    service, process = _repair(calls, [None, "summary"], clock, max_attempts=1)
    service.run()
    clock.now += 100
    service.run()
    assert service.pending()[0].gave_up

    assert service.retry("c1") == "summary"
    assert service.pending()[0].attempts == 0  # state was cleared on success


def test_retrying_an_active_call_is_refused():
    calls = CallService(ConversationService(InMemoryConversationRepository()))
    calls.start_call("live")
    service, _ = _repair(calls, [], Clock())
    with pytest.raises(CallNotRepairableError):
        service.retry("live")


def test_only_one_instance_sweeps_at_a_time():
    clock = Clock()
    service, _ = _repair(_completed_calls("c1"), [], clock)
    token = service._store.acquire_lock("post_call_repair", 60)
    assert token and service.run().skipped_reason


def test_post_call_repair_api():
    services = _services(post_call_repair_min_age_seconds=0)
    app = create_app(services)
    supervisor = _client(app, _user(services, UserRole.SUPERVISOR))
    icr = _client(app, _user(services, UserRole.ICR))
    icr.post("/api/v1/calls", json={"call_id": "c1"})
    icr.post(
        "/api/v1/calls/c1/utterances",
        json={
            "utterance_id": "u1",
            "transcript": "Hello",
            "speaker_role": "CUSTOMER",
            "languages": ["en"],
            "start_time": 0.0,
            "end_time": 1.0,
        },
    )
    services.call_service.end_call("c1", 5.0)  # completed without post-call processing

    assert icr.get("/api/v1/admin/post-call").status_code == 403
    status = supervisor.get("/api/v1/admin/post-call").json()
    assert [p["call_id"] for p in status["pending"]] == ["c1"]
    assert status["background_enabled"] is False

    assert supervisor.post("/api/v1/admin/post-call/c1/retry").json() == {
        "call_id": "c1",
        "repaired": True,
    }
    assert supervisor.get("/api/v1/admin/post-call").json()["pending"] == []
    assert supervisor.post("/api/v1/admin/post-call/repair").json()["pending"] == 0
    assert supervisor.post("/api/v1/admin/post-call/missing/retry").status_code == 404


def test_background_runner_runs_jobs_until_stopped():
    ran = threading.Event()
    runner = BackgroundJobRunner(
        [PeriodicJob("ok", 0.05, ran.set), PeriodicJob("off", 0, lambda: None)]
    )
    assert runner.job_names == ("ok",)
    runner.start()
    assert ran.wait(2)
    runner.stop()


# ---- User provisioning ----


def _users():
    repository = InMemoryUserRepository()
    return UserManagementService(repository, AuthService(repository))


def test_users_are_created_with_normalized_emails_and_checked_passwords():
    service = _users()
    user = service.create_user("  New.Agent@Example.com ", "password-123", UserRole.ICR)

    assert user.email == "new.agent@example.com"
    assert AuthService(service._repository).authenticate("New.Agent@example.com", "password-123")
    with pytest.raises(EmailAlreadyRegisteredError):
        service.create_user("new.agent@example.com", "password-123", UserRole.ICR)
    with pytest.raises(UserManagementError):
        service.create_user("short@example.com", "short", UserRole.ICR)


def test_the_last_active_admin_is_protected():
    service = _users()
    admin = service.create_user("admin@example.com", "password-123", UserRole.ADMIN)
    other = service.create_user("other@example.com", "password-123", UserRole.ADMIN)

    with pytest.raises(UserManagementError):
        service.update_user(admin.user_id, admin, is_active=False)  # yourself
    service.update_user(other.user_id, admin, role=UserRole.SUPERVISOR)
    with pytest.raises(UserManagementError):
        service.update_user(admin.user_id, other, role=UserRole.ICR)  # last admin


def test_bootstrap_admin_only_on_an_empty_system():
    service = _users()
    assert service.bootstrap_admin("", "x") is None
    admin = service.bootstrap_admin("root@example.com", "password-123456")
    assert admin.role is UserRole.ADMIN
    assert service.bootstrap_admin("second@example.com", "password-123456") is None


def test_user_admin_api():
    services = _services(bootstrap_admin_email="root@example.com", bootstrap_admin_password="password-123456")
    app = create_app(services)
    (root,) = services.user_management_service.list_users()
    admin = _client(app, root)
    supervisor_user = _user(services, UserRole.SUPERVISOR)

    assert _client(app, supervisor_user).get("/api/v1/admin/users").status_code == 403
    created = admin.post(
        "/api/v1/admin/users",
        json={"email": "agent@example.com", "password": "password-123", "role": "ICR"},
    )
    assert created.status_code == 201
    agent_id = created.json()["user_id"]
    assert admin.post(
        "/api/v1/admin/users",
        json={"email": "AGENT@example.com", "password": "password-123", "role": "ICR"},
    ).status_code == 409
    assert [u["email"] for u in admin.get("/api/v1/admin/users").json()] == [
        "root@example.com",
        "supervisor@example.com",
        "agent@example.com",
    ]

    agent = services.user_repository.get_by_id(agent_id)
    agent_client = _client(app, agent)
    assert agent_client.get("/api/v1/calls").status_code == 200
    updated = admin.patch(f"/api/v1/admin/users/{agent_id}", json={"is_active": False})
    assert updated.json()["is_active"] is False
    assert agent_client.get("/api/v1/calls").status_code == 401  # takes effect at once

    assert admin.patch(f"/api/v1/admin/users/{root.user_id}", json={"role": "ICR"}).status_code == 409
    assert admin.post(
        f"/api/v1/admin/users/{agent_id}/password", json={"password": "new-password-1"}
    ).status_code == 204
    assert admin.patch("/api/v1/admin/users/missing", json={"is_active": True}).status_code == 404
    login = TestClient(app).post(
        "/api/v1/auth/login", json={"email": "agent@example.com", "password": "new-password-1"}
    )
    assert login.status_code == 401  # still deactivated


# ---- Monitoring ----


def test_health_endpoints_report_dependencies():
    services = _services()
    client = TestClient(create_app(services))
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ok", "checks": {}}

    def broken():
        raise ConnectionError("down")

    services.health_checks.update({"database": lambda: None, "live_state": broken})
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "live_state": "unavailable"}


def test_requests_get_an_id_and_are_counted_by_route_template():
    services = _services()
    client = TestClient(create_app(services))

    generated = client.get("/api/v1/calls/some-call")
    echoed = client.get("/health/live", headers={"X-Request-ID": "abc-123"})
    ignored = client.get("/health/live", headers={"X-Request-ID": "bad id\n"})

    assert len(generated.headers["x-request-id"]) == 32
    assert echoed.headers["x-request-id"] == "abc-123"
    assert ignored.headers["x-request-id"] != "bad id\n"
    body = client.get("/metrics").text
    assert 'http_requests_total{method="GET",route="/api/v1/calls/{call_id}",status="401"}' in body
    assert "http_request_duration_seconds_bucket" in body
    assert 'calls{status="active"} 0' in body
    assert "telephony_streams_open" in body


def test_metrics_can_require_a_token(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.get_settings(), "metrics_token", "scrape-secret")
    client = TestClient(create_app(_services()))
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"}).status_code == 200


def test_metrics_render_in_prometheus_format():
    registry = MetricsRegistry()
    counter = registry.register(Counter("jobs_total", "Jobs.", ("outcome",)))
    histogram = registry.register(Histogram("latency_seconds", "Latency.", buckets=(0.1, 1)))
    registry.register(Gauge("broken", "Fails.", callback=lambda: 1 / 0))
    counter.inc('ok"quoted')
    histogram.observe(0.5)

    text = registry.render()

    assert 'jobs_total{outcome="ok\\"quoted"} 1' in text
    assert 'latency_seconds_bucket{le="0.1"} 0' in text
    assert 'latency_seconds_bucket{le="+Inf"} 1' in text
    assert "latency_seconds_count 1" in text
    assert "# broken unavailable" in text


# ---- Configuration checks ----


def _settings(**values) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_unsafe_production_configuration_is_refused():
    unsafe = _settings(
        app_env="production",
        auth_secret_key="short",
        plivo_auth_token="real",
        plivo_validate_signatures=False,
        plivo_stream_base_url="ws://insecure",
        live_state_store_provider="redis",
        cors_allowed_origins="*",
    )
    problems = configuration_problems(unsafe)
    assert len(problems) == 6
    with pytest.raises(UnsafeConfigurationError):
        check_configuration(unsafe, logging.getLogger("test"))


def test_safe_production_configuration_passes_and_development_only_warns(caplog):
    safe = _settings(
        app_env="production",
        auth_secret_key="x" * 40,
        database_url="postgresql+psycopg://u:p@db/app",
        cors_allowed_origins="https://calls.example.com",
    )
    assert configuration_problems(safe) == []
    check_configuration(safe, logging.getLogger("test"))

    with caplog.at_level(logging.WARNING):
        check_configuration(_settings(auth_secret_key="short"), logging.getLogger("test"))
    assert "AUTH_SECRET_KEY" in caplog.text


def test_example_placeholders_are_refused_in_production():
    from pathlib import Path

    example = Path(__file__).resolve().parents[2] / "deploy" / ".env.production.example"
    placeholder_keys = {
        line.split("=", 1)[0]
        for line in example.read_text(encoding="utf-8").splitlines()
        if "=replace-with-" in line and not line.startswith("#")
    }
    assert {"AUTH_SECRET_KEY", "GROQ_API_KEY", "SARVAM_API_KEY"} <= placeholder_keys

    unedited = _settings(
        app_env="production",
        auth_secret_key="replace-with-at-least-32-random-characters",
        groq_api_key="replace-with-your-groq-api-key",
        database_url="postgresql+psycopg://u:p@db/app",
        cors_allowed_origins="https://calls.example.com",
    )

    (problem,) = configuration_problems(unedited)
    assert "AUTH_SECRET_KEY" in problem and "GROQ_API_KEY" in problem
