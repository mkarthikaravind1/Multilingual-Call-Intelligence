"""The audit log (who did what, when) and the AI log (what the AI was asked
and answered, per call): what is and is not recorded, that request content
never reaches the audit log, the background writer, retention, the filters,
storage, and who may read."""

import itertools
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.ai.complaint.llm_provider import LLMComplaintProvider
from app.ai.llm.call_context import current_call_id, working_on_call
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.llm.groq_client import GroqLLMClient
from app.ai.llm.json_answer import UnusableAnswer, ask_for_json, decode_json
from app.ai.llm.logged_client import LoggedLLMClient
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentLabel, SentimentResult
from app.api.app_factory import API_V1_PREFIX, create_app
from app.api.audit import NOT_RECORDED, RECORDED_READS
from app.api.wiring import build_api_services
from app.composition import providers
from app.core.config import Settings
from app.core.production_checks import configuration_problems
from app.domain.user import User, UserRole
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import build_session_factory
from app.infrastructure.database.repositories.log_repositories import (
    PostgresAiLogRepository,
    PostgresAuditLogRepository,
)
from app.observability.metrics import LOG_ENTRIES_DROPPED
from app.security.jwt import create_access_token
from app.security.password import hash_password
from app.services.ai_log import (
    AiLog,
    AiLogFilter,
    AiLogMode,
    AiOutcome,
    InMemoryAiLogRepository,
    parse_mode,
)
from app.services.audit_log import (
    AuditEntry,
    AuditFilter,
    AuditLog,
    InMemoryAuditLogRepository,
)
from app.services.log_writer import BackgroundWriter

DAY = 86400.0


def _session_factory(request):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    request.addfinalizer(engine.dispose)
    return build_session_factory(engine)


@pytest.fixture(params=["memory", "sql"])
def ai_repository(request):
    if request.param == "memory":
        return InMemoryAiLogRepository()
    return PostgresAiLogRepository(_session_factory(request))


@pytest.fixture(params=["memory", "sql"])
def audit_repository(request):
    if request.param == "memory":
        return InMemoryAuditLogRepository()
    return PostgresAuditLogRepository(_session_factory(request))


# ---- The background writer ----


def test_the_writer_stores_entries_in_order_off_the_calling_thread():
    written: list[int] = []
    threads: set[str] = set()

    def write(batch: list[int]) -> None:
        threads.add(threading.current_thread().name)
        written.extend(batch)

    writer = BackgroundWriter(write, "test-order", batch_size=3)
    for number in range(10):
        assert writer.put(number)

    assert writer.flush()
    assert written == list(range(10))
    assert threads == {"log-writer-test-order"}


def test_a_failing_write_is_counted_and_the_next_entries_are_still_written():
    written: list[str] = []

    def write(batch: list[str]) -> None:
        if "bad" in batch:
            raise RuntimeError("database down")
        written.extend(batch)

    writer = BackgroundWriter(write, "test-failing", batch_size=1)
    writer.put("bad")
    writer.put("good")

    assert writer.flush()
    assert written == ["good"]
    assert LOG_ENTRIES_DROPPED.value("test-failing") == 1


def test_a_full_queue_drops_new_entries_instead_of_waiting():
    release = threading.Event()
    writer = BackgroundWriter(lambda batch: release.wait(5), "test-full", max_pending=2, batch_size=1)
    try:
        results = [writer.put(number) for number in range(6)]
    finally:
        release.set()

    assert results[0] is True
    assert results[-1] is False  # refused at once: nothing waited for the store
    assert LOG_ENTRIES_DROPPED.value("test-full") == results.count(False)
    assert writer.flush()


# ---- The AI log ----


def _record(log: AiLog, **changes) -> str | None:
    values = dict(
        call_id="call-1",
        task="complaints",
        model="test-model",
        prompt="CUSTOMER: The brakes still squeal.",
        answer='[{"category": "Workshop"}]',
        started_at=1000.0,
        duration_ms=420.5,
        outcome=AiOutcome.ANSWERED,
        prompt_tokens=120,
        completion_tokens=30,
    )
    values.update(changes)
    return log.record(**values)


def test_a_request_is_kept_with_its_prompt_answer_and_counts(ai_repository):
    log = AiLog(ai_repository)

    entry_id = _record(log)
    assert log.flush()

    entry = log.get(entry_id)
    assert (entry.call_id, entry.task, entry.model) == ("call-1", "complaints", "test-model")
    assert entry.prompt == "CUSTOMER: The brakes still squeal."
    assert entry.answer == '[{"category": "Workshop"}]'
    assert (entry.prompt_chars, entry.answer_chars) == (34, 26)
    assert (entry.prompt_tokens, entry.completion_tokens) == (120, 30)
    assert (entry.started_at, entry.duration_ms) == (1000.0, 420.5)
    assert (entry.outcome, entry.attempt, entry.note) == (AiOutcome.ANSWERED, 1, None)


def test_a_list_of_requests_leaves_out_their_text(ai_repository):
    log = AiLog(ai_repository)
    _record(log)
    log.flush()

    page = log.search(AiLogFilter())

    (entry,) = page.entries
    assert (entry.prompt, entry.answer) == (None, None)
    assert (entry.prompt_chars, entry.answer_chars) == (34, 26)


def test_details_mode_keeps_everything_but_what_was_said(ai_repository):
    log = AiLog(ai_repository, mode=AiLogMode.DETAILS)

    entry_id = _record(log)
    log.flush()
    entry = log.get(entry_id)

    assert (entry.prompt, entry.answer) == (None, None)
    assert (entry.prompt_chars, entry.prompt_tokens, entry.task) == (34, 120, "complaints")


def test_off_keeps_nothing():
    repository = InMemoryAiLogRepository()
    log = AiLog(repository, mode=AiLogMode.OFF)

    assert _record(log) is None
    log.flush()
    assert log.search(AiLogFilter()).total == 0
    assert not log.enabled


def test_a_mistyped_mode_never_keeps_customer_speech():
    assert parse_mode(" Full ") is AiLogMode.FULL
    assert parse_mode("off") is AiLogMode.OFF
    assert parse_mode("everything") is AiLogMode.DETAILS
    assert parse_mode("") is AiLogMode.DETAILS


def test_an_answer_can_be_marked_unusable_afterwards(ai_repository):
    log = AiLog(ai_repository)
    entry_id = _record(log)

    log.mark_unusable(entry_id, "response is not valid JSON")
    log.flush()

    entry = log.get(entry_id)
    assert (entry.outcome, entry.note) == (AiOutcome.UNUSABLE, "response is not valid JSON")
    assert entry.answer == '[{"category": "Workshop"}]'  # what it said is still there


def test_a_long_error_is_cut_short(ai_repository):
    log = AiLog(ai_repository)
    entry_id = _record(log, outcome=AiOutcome.FAILED, answer=None, note="x" * 2000)
    log.flush()

    assert len(log.get(entry_id).note) == 503


def test_requests_are_found_by_call_task_outcome_and_time_newest_first(ai_repository):
    log = AiLog(ai_repository)
    _record(log, started_at=100.0, task="complaints")
    _record(log, started_at=200.0, task="sentiment")
    _record(log, started_at=300.0, task="summary", call_id="call-2")
    _record(log, started_at=400.0, task="sentiment", outcome=AiOutcome.FAILED, answer=None,
            prompt_tokens=None, completion_tokens=None)
    _record(log, started_at=500.0, task="emerging_themes", call_id=None)
    log.flush()

    def tasks(**filters):
        return [e.task for e in log.search(AiLogFilter(**filters)).entries]

    assert tasks() == ["emerging_themes", "sentiment", "summary", "sentiment", "complaints"]
    assert tasks(call_id="call-1") == ["sentiment", "sentiment", "complaints"]
    assert tasks(task="sentiment") == ["sentiment", "sentiment"]
    assert tasks(outcome=AiOutcome.FAILED) == ["sentiment"]
    assert tasks(started_from=200.0, started_to=400.0) == ["summary", "sentiment"]
    assert log.tasks() == ("complaints", "emerging_themes", "sentiment", "summary")

    page = log.search(AiLogFilter(), limit=2, offset=2)
    assert ([e.task for e in page.entries], page.total) == (["summary", "sentiment"], 5)


def test_totals_cover_everything_the_filters_match_not_just_the_page(ai_repository):
    log = AiLog(ai_repository)
    _record(log, started_at=1.0)
    _record(log, started_at=2.0, prompt_tokens=80, completion_tokens=20)
    _record(log, started_at=3.0, outcome=AiOutcome.FAILED, answer=None,
            prompt_tokens=None, completion_tokens=None)
    _record(log, started_at=4.0, call_id="call-2", prompt_tokens=999, completion_tokens=1)
    log.flush()

    totals = log.search(AiLogFilter(call_id="call-1"), limit=1).totals

    assert (totals.requests, totals.prompt_tokens, totals.completion_tokens) == (3, 200, 50)
    assert (totals.total_tokens, totals.uncounted) == (250, 1)


def test_old_requests_are_removed_after_the_retention_period(ai_repository):
    now = [100 * DAY]
    log = AiLog(ai_repository, retention_days=30, clock=lambda: now[0])
    _record(log, started_at=69 * DAY, task="old")
    _record(log, started_at=71 * DAY, task="recent")
    log.flush()

    assert log.purge_expired() == 1
    assert [e.task for e in log.search(AiLogFilter()).entries] == ["recent"]
    assert log.purge_expired() == 0


# ---- The logged LLM client ----


class _LLM(LLMClient):
    def __init__(self, *answers: str | Exception) -> None:
        self.answers = list(answers)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return LLMResponse(text=answer, model="served-model", prompt_tokens=11, completion_tokens=4)


def _logged(*answers, mode=AiLogMode.FULL) -> tuple[LoggedLLMClient, AiLog]:
    log = AiLog(InMemoryAiLogRepository(), mode=mode)
    ticks = itertools.count(5000)
    return LoggedLLMClient(_LLM(*answers), log, "configured-model", clock=lambda: float(next(ticks))), log


def _entries(log: AiLog):
    assert log.flush()
    listed = log.search(AiLogFilter(), limit=200).entries
    return [log.get(entry.entry_id) for entry in reversed(listed)]


def test_every_request_is_logged_with_the_call_being_worked_on():
    client, log = _logged("the answer")

    with working_on_call("call-7"):
        response = client.complete(LLMRequest(prompt="the prompt", task="summary"))

    (entry,) = _entries(log)
    assert response.text == "the answer"
    assert response.log_id == entry.entry_id
    assert (entry.call_id, entry.task, entry.model) == ("call-7", "summary", "served-model")
    assert (entry.prompt, entry.answer) == ("the prompt", "the answer")
    assert (entry.prompt_tokens, entry.completion_tokens) == (11, 4)
    assert (entry.started_at, entry.outcome) == (5000.0, AiOutcome.ANSWERED)
    assert entry.duration_ms >= 0
    assert current_call_id() is None  # the call is forgotten afterwards


def test_a_request_outside_any_call_is_logged_without_one():
    client, log = _logged("themes")

    client.complete(LLMRequest(prompt="p", task="emerging_themes"))

    assert _entries(log)[0].call_id is None


def test_a_request_without_a_task_is_filed_under_other():
    client, log = _logged("x")

    client.complete(LLMRequest(prompt="p"))

    assert _entries(log)[0].task == "other"


def test_a_failed_request_is_logged_and_still_raises():
    client, log = _logged(RuntimeError("rate limited: try again in 20s"))

    with pytest.raises(RuntimeError), working_on_call("call-7"):
        client.complete(LLMRequest(prompt="the prompt", task="sentiment"))

    (entry,) = _entries(log)
    assert (entry.outcome, entry.note) == (AiOutcome.FAILED, "rate limited: try again in 20s")
    assert (entry.answer, entry.model, entry.call_id) == (None, "configured-model", "call-7")
    assert entry.prompt_tokens is None


def test_an_unreadable_answer_and_the_second_request_are_both_logged():
    client, log = _logged("Sorry, I cannot.", '{"ok": true}')

    result = ask_for_json(client, LLMRequest(prompt="Give JSON."), decode_json, "complaints")

    first, second = _entries(log)
    assert result == {"ok": True}
    assert (first.task, first.attempt, first.outcome) == ("complaints", 1, AiOutcome.UNUSABLE)
    assert first.note == "response is not valid JSON"
    assert first.answer == "Sorry, I cannot."
    assert (second.task, second.attempt, second.outcome) == ("complaints", 2, AiOutcome.ANSWERED)
    assert second.prompt.startswith("Give JSON.") and len(second.prompt) > len(first.prompt)


def test_two_unreadable_answers_are_both_marked_unusable():
    client, log = _logged("no", "still no")

    with pytest.raises(UnusableAnswer):
        ask_for_json(client, LLMRequest(prompt="Give JSON."), decode_json, "sentiment")

    assert [e.outcome for e in _entries(log)] == [AiOutcome.UNUSABLE, AiOutcome.UNUSABLE]


def test_a_task_named_on_the_request_is_not_overwritten():
    client, log = _logged("{}")

    ask_for_json(client, LLMRequest(prompt="p", task="live_analysis"), decode_json, "x")

    assert _entries(log)[0].task == "live_analysis"


def test_a_log_that_cannot_be_written_never_fails_the_request():
    log = MagicMock()
    log.record.side_effect = RuntimeError("log broken")
    log.mark_unusable.side_effect = RuntimeError("log broken")
    client = LoggedLLMClient(_LLM("fine"), log, "m")

    response = client.complete(LLMRequest(prompt="p"))
    client.report_unusable(response, "why")
    response.log_id = "abc"
    client.report_unusable(response, "why")

    assert (response.text, log.mark_unusable.call_count) == ("fine", 1)


def test_the_providers_name_their_task():
    from app.domain.conversation import Conversation
    from app.domain.utterance import SpeakerRole, Utterance

    client, log = _logged("[]")
    call = Conversation("call-9")
    call.add_utterance(Utterance("u1", "Too expensive.", SpeakerRole.CUSTOMER, ("en",), 0.0, 1.0))

    LLMComplaintProvider(client).detect(call)

    assert _entries(log)[0].task == "complaints"


@patch("app.ai.llm.groq_client.Groq")
def test_the_groq_client_reports_the_model_and_the_token_counts(mock_groq):
    response = MagicMock()
    response.choices[0].message.content = "hello"
    response.usage.prompt_tokens = 321
    response.usage.completion_tokens = 45
    mock_groq.return_value.chat.completions.create.return_value = response

    answer = GroqLLMClient(model="test-model").complete(LLMRequest(prompt="hi"))

    assert (answer.model, answer.prompt_tokens, answer.completion_tokens) == ("test-model", 321, 45)


@patch("app.ai.llm.groq_client.Groq")
def test_missing_token_counts_are_left_empty(mock_groq):
    response = MagicMock()
    response.choices[0].message.content = "hello"
    response.usage = None
    mock_groq.return_value.chat.completions.create.return_value = response

    answer = GroqLLMClient(model="test-model").complete(LLMRequest(prompt="hi"))

    assert (answer.prompt_tokens, answer.completion_tokens) == (None, None)


@patch("app.ai.llm.groq_client.Groq")
def test_llm_clients_are_logged_once_the_log_is_in_use(mock_groq):
    settings = Settings(_env_file=None, llm_provider="groq")  # type: ignore[call-arg]
    try:
        assert isinstance(providers.create_llm_client(settings), GroqLLMClient)

        providers.use_ai_log(AiLog(InMemoryAiLogRepository()))
        assert isinstance(providers.create_llm_client(settings), LoggedLLMClient)
        assert isinstance(
            providers.create_llm_client(settings, model="other", max_retries=0), LoggedLLMClient
        )

        providers.use_ai_log(AiLog(InMemoryAiLogRepository(), mode=AiLogMode.OFF))
        assert isinstance(providers.create_llm_client(settings), GroqLLMClient)
    finally:
        providers.use_ai_log(None)


# ---- The audit log ----


def _audit(**changes) -> AuditEntry:
    values = dict(
        occurred_at=1000.0,
        action="create_user",
        method="POST",
        path="/api/v1/admin/users",
        status_code=201,
        user_id="admin-1",
        role="ADMIN",
    )
    values.update(changes)
    return AuditEntry(**values)


def test_an_entry_is_stored_as_given(audit_repository):
    log = AuditLog(audit_repository)

    log.record(
        _audit(
            target_type="user",
            target_id="u-9",
            ip_address="10.0.0.5",
            request_id="req-1",
            detail={"email": "a@example.com"},
        )
    )
    assert log.flush()

    (entry,) = log.search(AuditFilter()).entries
    assert entry.entry_id is not None
    assert (entry.user_id, entry.role, entry.action) == ("admin-1", "ADMIN", "create_user")
    assert (entry.method, entry.path, entry.status_code) == ("POST", "/api/v1/admin/users", 201)
    assert (entry.target_type, entry.target_id) == ("user", "u-9")
    assert (entry.ip_address, entry.request_id) == ("10.0.0.5", "req-1")
    assert entry.detail == {"email": "a@example.com"}
    assert entry.succeeded


def test_entries_are_found_by_user_action_result_target_and_time(audit_repository):
    log = AuditLog(audit_repository)
    log.record(_audit(occurred_at=100.0))
    log.record(_audit(occurred_at=200.0, action="hold_call", user_id="icr-1", target_id="c1"))
    log.record(_audit(occurred_at=300.0, action="login", user_id=None, status_code=401))
    log.record(_audit(occurred_at=400.0, action="hold_call", status_code=409, target_id="c2"))
    log.flush()

    def found(**filters):
        return [e.occurred_at for e in log.search(AuditFilter(**filters)).entries]

    assert found() == [400.0, 300.0, 200.0, 100.0]
    assert found(user_id="admin-1") == [400.0, 100.0]
    assert found(action="hold_call") == [400.0, 200.0]
    assert found(succeeded=False) == [400.0, 300.0]
    assert found(succeeded=True) == [200.0, 100.0]
    assert found(target_id="c1") == [200.0]
    assert found(occurred_from=200.0, occurred_to=400.0) == [300.0, 200.0]
    assert log.actions() == ("create_user", "hold_call", "login")

    page = log.search(AuditFilter(), limit=2, offset=1)
    assert ([e.occurred_at for e in page.entries], page.total) == ([300.0, 200.0], 4)


def test_old_entries_are_removed_after_the_retention_period(audit_repository):
    now = [400 * DAY]
    log = AuditLog(audit_repository, retention_days=365, clock=lambda: now[0])
    log.record(_audit(occurred_at=34 * DAY, action="old"))
    log.record(_audit(occurred_at=36 * DAY, action="recent"))
    log.flush()

    assert log.purge_expired() == 1
    assert [e.action for e in log.search(AuditFilter()).entries] == ["recent"]


# ---- What the application records ----


class _Calm(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEUTRAL, 0.7, "Calm.")


class _NoQuestions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


PASSWORD = "correct-horse-battery"


class _Api:
    def __init__(self, llm_answers=("[]",) * 20) -> None:
        self.ai_log = AiLog(InMemoryAiLogRepository())
        self.llm = _LLM(*llm_answers)
        self.services = build_api_services(
            LLMComplaintProvider(LoggedLLMClient(self.llm, self.ai_log, "test-model")),
            _Calm(),
            _NoQuestions(),
            Settings(_env_file=None),  # type: ignore[call-arg]
            ai_log=self.ai_log,
        )
        self.client = TestClient(create_app(self.services))

    def user(self, user_id: str, role: UserRole) -> dict[str, str]:
        user = User(
            user_id, f"{user_id}@example.com", hash_password(PASSWORD), role, True, time.time(),
            display_name=user_id.title(),
        )
        self.services.user_repository.save(user)
        return {"Authorization": f"Bearer {create_access_token(user)}"}

    def start_call(self, headers: dict[str, str], call_id: str = "call-a") -> str:
        response = self.client.post("/api/v1/calls", json={"call_id": call_id}, headers=headers)
        assert response.status_code == 201
        return call_id

    def audit(self, **filters) -> list[AuditEntry]:
        """Oldest first."""
        assert self.services.audit_log.flush()
        return list(reversed(self.services.audit_log.search(AuditFilter(**filters), 200).entries))


def test_a_change_is_recorded_with_who_what_and_the_result():
    api = _Api()
    admin = api.user("admin-1", UserRole.ADMIN)
    before = time.time()

    response = api.client.post(
        "/api/v1/admin/complaint-categories",
        json={"name": "Loaner Vehicle", "description": "No courtesy car."},
        headers=admin,
    )

    (entry,) = api.audit()
    assert response.status_code == 201
    assert (entry.user_id, entry.role) == ("admin-1", "ADMIN")
    assert (entry.action, entry.method) == ("add_complaint_category", "POST")
    assert entry.path == "/api/v1/admin/complaint-categories"
    assert (entry.status_code, entry.succeeded) == (201, True)
    assert before <= entry.occurred_at <= time.time()
    assert entry.request_id == response.headers["x-request-id"]
    assert entry.ip_address == "testclient"
    # What it made, though its address names nothing.
    assert (entry.target_type, entry.target_id) == ("category", response.json()["key"])


def test_what_a_change_was_done_to_comes_from_its_address():
    api = _Api()
    icr = api.user("icr-1", UserRole.ICR)
    call_id = api.start_call(icr)

    api.client.post(f"/api/v1/calls/{call_id}/hold", headers=icr)

    start, hold = api.audit()
    assert (start.action, start.target_type, start.target_id) == ("start_call", "call", call_id)
    assert (hold.target_type, hold.target_id, hold.user_id) == ("call", call_id, "icr-1")


def test_what_was_sent_never_reaches_the_audit_log():
    api = _Api()
    admin = api.user("admin-1", UserRole.ADMIN)
    icr = api.user("icr-1", UserRole.ICR)
    call_id = api.start_call(icr)

    api.client.post(
        "/api/v1/admin/users",
        json={"email": "new.person@example.com", "password": "a-very-secret-pw", "role": "ICR"},
        headers=admin,
    )
    api.client.post(
        f"/api/v1/calls/{call_id}/utterances",
        json={
            "utterance_id": "u1",
            "transcript": "My number is 9876543210 and the brakes squeal.",
            "speaker_role": "CUSTOMER",
            "languages": ["en"],
            "start_time": 0.0,
            "end_time": 2.0,
        },
        headers=icr,
    )
    api.client.post(
        "/api/v1/auth/login", json={"email": "icr-1@example.com", "password": "wrong-password"}
    )

    stored = repr(api.audit())
    assert len(api.audit()) == 4
    for secret in ("a-very-secret-pw", "new.person", "9876543210", "brakes", "wrong-password"):
        assert secret not in stored


def test_a_refused_change_is_recorded_as_failed_with_who_tried():
    api = _Api()
    icr = api.user("icr-1", UserRole.ICR)

    response = api.client.post(
        "/api/v1/admin/complaint-categories", json={"name": "Mine"}, headers=icr
    )

    (entry,) = api.audit()
    assert response.status_code == 403
    assert (entry.user_id, entry.role, entry.status_code, entry.succeeded) == (
        "icr-1", "ICR", 403, False,
    )


def test_a_change_tried_without_signing_in_is_recorded_with_nobody():
    api = _Api()

    api.client.post("/api/v1/admin/complaint-categories", json={"name": "Mine"})
    api.client.post(
        "/api/v1/admin/complaint-categories",
        json={"name": "Mine"},
        headers={"Authorization": "Bearer not-a-token"},
    )

    first, second = api.audit()
    assert [(e.user_id, e.role, e.status_code) for e in (first, second)] == [
        (None, None, 401), (None, None, 401),
    ]


def test_signing_in_is_recorded_and_so_is_a_failed_attempt():
    api = _Api()
    api.user("icr-1", UserRole.ICR)

    ok = api.client.post(
        "/api/v1/auth/login", json={"email": "icr-1@example.com", "password": PASSWORD}
    )
    bad = api.client.post(
        "/api/v1/auth/login", json={"email": "ICR-1@example.com", "password": "guess"}
    )

    success, failure = api.audit()
    assert (ok.status_code, bad.status_code) == (200, 401)
    assert (success.action, success.user_id, success.role) == ("login", "icr-1", "ICR")
    assert success.detail is None
    assert (failure.user_id, failure.status_code) == (None, 401)
    assert failure.detail == {"email": "icr-1@example.com"}


def test_reading_is_not_recorded_except_the_reads_that_matter():
    api = _Api()
    admin = api.user("admin-1", UserRole.ADMIN)

    api.client.get("/api/v1/admin/users", headers=admin)
    api.client.get("/api/v1/calls", headers=admin)
    assert api.audit() == []

    api.client.get("/api/v1/admin/audit-log", headers=admin)
    api.client.get("/api/v1/admin/ai-log", headers=admin)
    api.client.get("/api/v1/admin/ai-log/missing", headers=admin)
    api.client.get("/api/v1/reports/complaints/export?format=csv", headers=admin)
    api.client.get("/api/v1/price-list/export", headers=admin)
    api.client.get("/api/v1/calls/some-call/recording/audio", headers=admin)

    entries = api.audit()
    assert [e.action for e in entries] == [
        "read_audit_log",
        "read_ai_log",
        "read_ai_log_entry",
        "export_complaint_report",
        "export_price_list",
        "get_call_recording_audio",
    ]
    assert all(e.method == "GET" and e.user_id == "admin-1" for e in entries)
    assert (entries[2].target_type, entries[2].target_id, entries[2].status_code) == (
        "entry", "missing", 404,
    )
    assert (entries[5].target_type, entries[5].target_id) == ("call", "some-call")


def test_requests_that_change_nothing_are_left_out():
    api = _Api()
    icr = api.user("icr-1", UserRole.ICR)
    call_id = api.start_call(icr)

    assert api.client.post("/api/v1/auth/refresh", headers=icr).status_code == 200
    assert api.client.post(f"/api/v1/calls/{call_id}/live-token", headers=icr).status_code == 200

    assert [e.action for e in api.audit()] == ["start_call"]


def test_the_listed_exceptions_are_real_endpoints():
    declared = {
        (path.removeprefix(API_V1_PREFIX), method.upper())
        for path, methods in _Api().client.app.openapi()["paths"].items()
        for method in methods
    }
    paths = {path for path, _ in declared}

    assert NOT_RECORDED <= paths
    assert all((path, "GET") in declared for path in RECORDED_READS)
    assert not any((path, "GET") in declared for path in NOT_RECORDED)


def test_a_telephony_webhook_is_recorded_as_the_telephony_provider():
    api = _Api()

    api.client.post("/api/v1/telephony/plivo/status", data={"CallUUID": "abc"})

    (entry,) = api.audit()
    assert (entry.user_id, entry.role, entry.action) == (None, "telephony", entry.action)
    assert entry.path == "/api/v1/telephony/plivo/status"


def test_an_unknown_address_is_not_recorded():
    api = _Api()

    api.client.post("/api/v1/nothing-here", json={})

    assert api.audit() == []


def test_a_broken_audit_log_never_fails_the_request():
    api = _Api()
    admin = api.user("admin-1", UserRole.ADMIN)
    with patch.object(api.services.audit_log, "record", side_effect=RuntimeError("down")):
        response = api.client.post(
            "/api/v1/admin/complaint-categories", json={"name": "Loaner"}, headers=admin
        )

    assert response.status_code == 201


# ---- Reading the audit log ----


def test_an_administrator_reads_the_audit_log_with_names_and_filters():
    api = _Api()
    admin = api.user("admin-1", UserRole.ADMIN)
    icr = api.user("icr-1", UserRole.ICR)
    call_id = api.start_call(icr)
    api.client.post(f"/api/v1/calls/{call_id}/hold", headers=icr)
    api.client.post("/api/v1/calls/missing/hold", headers=icr)  # no such call
    api.client.post("/api/v1/admin/complaint-categories", json={"name": "Loaner"}, headers=admin)
    api.services.audit_log.flush()

    def read(**params):
        api.services.audit_log.flush()
        response = api.client.get("/api/v1/admin/audit-log", params=params, headers=admin)
        assert response.status_code == 200
        return response.json()

    body = read()
    assert body["total"] == 4
    assert [e["action"] for e in body["entries"]] == [
        "add_complaint_category", "hold_call", "hold_call", "start_call",
    ]
    assert body["entries"][0]["user_name"] == "Admin-1"
    assert body["entries"][1]["succeeded"] is False
    assert body["retention_days"] == 365
    assert {"user_id": "icr-1", "name": "Icr-1"} in body["users"]
    assert set(body["actions"]) >= {"add_complaint_category", "hold_call", "start_call"}

    assert [e["action"] for e in read(user_id="icr-1", action="hold_call")["entries"]] == [
        "hold_call", "hold_call",
    ]
    failed = read(succeeded="false", user_id="icr-1")["entries"]
    assert [(e["action"], e["status_code"], e["target_id"]) for e in failed] == [
        ("hold_call", 404, "missing")
    ]
    assert [e["action"] for e in read(target_id=call_id)["entries"]] == ["hold_call", "start_call"]
    assert read(user_id="icr-1", limit=1, offset=2)["entries"][0]["action"] == "start_call"
    assert read(occurred_to=1.0)["total"] == 0
    # Each of those reads is in the log too.
    assert read(action="read_audit_log")["total"] >= 5


@pytest.mark.parametrize("role", [UserRole.ICR, UserRole.SUPERVISOR])
def test_only_administrators_read_the_logs(role):
    api = _Api()
    headers = api.user("someone", role)

    for url in ("/api/v1/admin/audit-log", "/api/v1/admin/ai-log", "/api/v1/admin/ai-log/x"):
        assert api.client.get(url, headers=headers).status_code == 403
        assert api.client.get(url).status_code == 401

    # The attempts themselves are on record.
    assert [e.status_code for e in api.audit(user_id="someone")] == [403, 403, 403]


def test_a_page_size_beyond_the_limit_is_refused():
    api = _Api()
    admin = api.user("admin-1", UserRole.ADMIN)

    for url in ("/api/v1/admin/audit-log", "/api/v1/admin/ai-log"):
        assert api.client.get(url, params={"limit": 201}, headers=admin).status_code == 422
        assert api.client.get(url, params={"offset": -1}, headers=admin).status_code == 422


# ---- The AI log of a real call, and reading it ----


def _say(api: _Api, headers, call_id: str, text: str, utterance_id: str = "u1"):
    return api.client.post(
        f"/api/v1/calls/{call_id}/utterances",
        json={
            "utterance_id": utterance_id,
            "transcript": text,
            "speaker_role": "CUSTOMER",
            "languages": ["en"],
            "start_time": 0.0,
            "end_time": 2.0,
        },
        headers=headers,
    )


def test_the_ai_requests_of_a_call_are_logged_against_it():
    api = _Api(llm_answers=("not json", '[{"category": "Cost", "confidence": 0.9, "evidence": "Too costly."}]') + ("[]",) * 10)
    icr = api.user("icr-1", UserRole.ICR)
    admin = api.user("admin-1", UserRole.ADMIN)
    call_id = api.start_call(icr)

    assert _say(api, icr, call_id, "The bill was far too costly.").status_code == 200
    api.ai_log.flush()

    body = api.client.get("/api/v1/admin/ai-log", params={"call_id": call_id}, headers=admin).json()
    assert body["total"] == 2
    assert body["mode"] == "full"
    assert body["retention_days"] == 30
    assert body["tasks"] == ["complaints"]
    assert body["totals"] == {
        "requests": 2, "prompt_tokens": 22, "completion_tokens": 8, "total_tokens": 30,
        "uncounted": 0,
    }
    second, first = body["entries"]
    assert (first["outcome"], first["attempt"]) == ("unusable", 1)
    assert (second["outcome"], second["attempt"], second["call_id"]) == ("answered", 2, call_id)
    assert "prompt" not in first and "answer" not in first

    detail = api.client.get(f"/api/v1/admin/ai-log/{first['entry_id']}", headers=admin).json()
    assert "The bill was far too costly." in detail["prompt"]
    assert detail["answer"] == "not json"
    assert detail["note"] == "response is not valid JSON"

    other = api.client.get("/api/v1/admin/ai-log", params={"call_id": "other"}, headers=admin)
    assert other.json()["total"] == 0
    assert api.client.get("/api/v1/admin/ai-log/nope", headers=admin).status_code == 404


def test_the_ai_log_is_filtered_by_task_outcome_and_time():
    api = _Api()
    admin = api.user("admin-1", UserRole.ADMIN)
    _record(api.ai_log, started_at=100.0, task="sentiment")
    _record(api.ai_log, started_at=200.0, task="summary", outcome=AiOutcome.FAILED, answer=None)
    api.ai_log.flush()

    def tasks(**params):
        body = api.client.get("/api/v1/admin/ai-log", params=params, headers=admin).json()
        return [e["task"] for e in body["entries"]]

    assert tasks() == ["summary", "sentiment"]
    assert tasks(task="sentiment") == ["sentiment"]
    assert tasks(outcome="failed") == ["summary"]
    assert tasks(started_from=150.0) == ["summary"]
    assert tasks(started_to=150.0, call_id="  call-1 ") == ["sentiment"]
    assert api.client.get(
        "/api/v1/admin/ai-log", params={"outcome": "nonsense"}, headers=admin
    ).status_code == 422


# ---- Retention jobs and configuration ----


def test_both_logs_are_cleaned_by_background_jobs():
    def jobs(**settings) -> dict[str, float]:
        services = build_api_services(
            LLMComplaintProvider(_LLM()), _Calm(), _NoQuestions(),
            Settings(_env_file=None, **settings),  # type: ignore[call-arg]
        )
        return {job.name: job.interval_seconds for job in services.background_jobs._jobs}

    assert jobs()["audit_log_retention"] == 3600.0
    assert jobs()["ai_log_retention"] == 3600.0
    assert "audit_log_retention" not in jobs(log_retention_sweep_seconds=0)
    assert "ai_log_retention" not in jobs(log_retention_sweep_seconds=0)


def test_the_retention_periods_come_from_the_settings():
    services = build_api_services(
        LLMComplaintProvider(_LLM()), _Calm(), _NoQuestions(),
        Settings(  # type: ignore[call-arg]
            _env_file=None, audit_log_retention_days=90, ai_log_retention_days=7,
            ai_log_mode="details",
        ),
    )

    assert services.audit_log.retention_days == 90
    assert (services.ai_log.retention_days, services.ai_log.mode) == (7, AiLogMode.DETAILS)


def test_the_defaults_are_a_year_of_audit_log_and_thirty_days_of_full_ai_log():
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.audit_log_retention_days == 365
    assert (settings.ai_log_retention_days, settings.ai_log_mode) == (30, "full")


@pytest.mark.parametrize(
    ("settings", "problem"),
    [
        ({"audit_log_retention_days": 0}, "AUDIT_LOG_RETENTION_DAYS must be more than 0."),
        ({"ai_log_retention_days": 0}, "AI_LOG_RETENTION_DAYS must be more than 0."),
        ({"ai_log_mode": "everything"}, "AI_LOG_MODE must be full, details or off."),
    ],
)
def test_production_refuses_unusable_log_settings(settings, problem):
    assert problem in configuration_problems(Settings(_env_file=None, **settings))  # type: ignore[call-arg]


def test_production_accepts_the_default_log_settings_and_no_retention_when_off():
    def log_problems(**settings) -> list[str]:
        problems = configuration_problems(Settings(_env_file=None, **settings))  # type: ignore[call-arg]
        return [p for p in problems if "_LOG_" in p]

    assert log_problems() == []
    assert log_problems(ai_log_mode="off", ai_log_retention_days=0) == []
