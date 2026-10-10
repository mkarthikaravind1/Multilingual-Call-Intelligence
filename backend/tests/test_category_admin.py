"""An administrator adds, renames, retires and restores complaint
categories: what detection is told, the name rules, that complaints stored
under a former name follow the category to its new one (reports, a call's
own pages, the Complaints page), storage, and who may do it."""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.ai.complaint.llm_provider import LLMComplaintProvider
from app.ai.complaint.provider import ComplaintDetectionProvider, ComplaintDetectionResult
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentLabel, SentimentResult
from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.core.config import Settings
from app.core.constants import COMPLAINT_CATEGORIES
from app.domain.complaint_category import ComplaintCategory
from app.domain.conversation import Conversation
from app.domain.emerging_complaint_candidate import (
    EmergingComplaintCandidate,
    EmergingComplaintReviewStatus,
)
from app.domain.managed_category import (
    InMemoryManagedCategoryRepository,
    ManagedCategory,
    built_in_key,
    theme_key,
)
from app.domain.user import User, UserRole
from app.domain.utterance import SpeakerRole, Utterance
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import build_session_factory
from app.infrastructure.database.repositories.managed_category_repository import (
    PostgresManagedCategoryRepository,
)
from app.security.jwt import create_access_token
from app.services.complaint_category_admin import (
    CategoryAdminError,
    CategoryNotFoundError,
    ComplaintCategoryAdminService,
)
from app.services.complaint_category_catalog import ComplaintCategoryCatalog
from app.services.emerging_complaint_repository import InMemoryEmergingComplaintRepository
from app.services.reporting import (
    RenamingReportSource,
    ReportCall,
    ReportComplaint,
    ReportFilters,
    ReportService,
    ReportSource,
)

BY = "admin-1"


def _theme(candidate_id: str = "t1", name: str = "Loaner Car") -> EmergingComplaintCandidate:
    return EmergingComplaintCandidate(
        candidate_id=candidate_id,
        proposed_name=name,
        description="No courtesy car was offered.",
        call_ids=("c1", "c2"),
        evidence=("Nobody offered me a car.",),
        occurrence_count=2,
        confidence=0.8,
        first_seen_at=1.0,
        last_seen_at=2.0,
        status=EmergingComplaintReviewStatus.ACCEPTED,
        category_name=name,
    )


class _Setup:
    def __init__(self, managed=None, themes=()) -> None:
        self.themes = InMemoryEmergingComplaintRepository()
        for theme in themes:
            self.themes.save(theme)
        self.managed = managed or InMemoryManagedCategoryRepository()
        self.catalog = ComplaintCategoryCatalog(
            self.themes, cache_seconds=30.0, managed=self.managed
        )
        self.clock = [1000.0]
        self.admin = ComplaintCategoryAdminService(
            self.catalog, self.managed, clock=lambda: self.clock[0]
        )

    def names(self) -> tuple[str, ...]:
        return self.catalog.names()


@pytest.fixture(params=["memory", "sql"])
def setup(request) -> _Setup:
    if request.param == "memory":
        return _Setup()
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    request.addfinalizer(engine.dispose)
    return _Setup(PostgresManagedCategoryRepository(build_session_factory(engine)))


# ---- Add ----


def test_an_added_category_is_in_use_at_once_between_the_built_ins_and_other(setup):
    entry = setup.admin.add("  Loaner   Vehicle ", "No courtesy car was offered.", BY)

    assert (entry.category.name, entry.source, entry.is_retired) == ("Loaner Vehicle", "admin", False)
    assert entry.key.startswith("admin:")
    assert entry.category.description == "No courtesy car was offered."
    # No wait for the cache: this instance sees it now.
    assert setup.names() == (*COMPLAINT_CATEGORIES[:-1], "Loaner Vehicle", "Other")
    assert not entry.category.built_in
    stored = setup.managed.get(entry.key)
    assert (stored.updated_by, stored.updated_at) == (BY, 1000.0)


def test_the_detector_is_told_an_added_category_and_what_counts_as_it(setup):
    setup.admin.add("Loaner Vehicle", "No courtesy car was offered.", BY)

    class _LLM(LLMClient):
        prompt = ""

        def complete(self, request: LLMRequest) -> LLMResponse:
            self.prompt = request.prompt
            return LLMResponse(
                text='[{"category": "loaner vehicle", "confidence": 0.9, "evidence": "No car."}]'
            )

    llm = _LLM()
    call = Conversation("c1")
    call.add_utterance(Utterance("u1", "No loaner car.", SpeakerRole.CUSTOMER, ("en",), 0.0, 1.0))

    (found,) = LLMComplaintProvider(llm, setup.catalog).detect(call)

    assert "- Loaner Vehicle: No courtesy car was offered." in llm.prompt
    assert found.category == "Loaner Vehicle"


@pytest.mark.parametrize("name", ["", "   ", "x" * 41])
def test_a_category_needs_a_name_of_a_sane_length(setup, name):
    with pytest.raises(CategoryAdminError):
        setup.admin.add(name, None, BY)


def test_a_description_has_a_limit_and_an_empty_one_is_none(setup):
    assert setup.admin.add("Loaner Vehicle", "   ", BY).category.description is None
    with pytest.raises(CategoryAdminError):
        setup.admin.add("Valet", "x" * 501, BY)


@pytest.mark.parametrize("taken", ["Cost", "cost", "  HYGIENE ", "Other"])
def test_a_name_another_category_has_cannot_be_used(setup, taken):
    with pytest.raises(CategoryAdminError, match="is taken"):
        setup.admin.add(taken, None, BY)


# ---- Rename ----


def test_a_renamed_category_keeps_its_former_name_for_old_complaints(setup):
    entry = setup.admin.add("Loaner Vehicle", "No courtesy car.", BY)

    renamed = setup.admin.rename(entry.key, "Courtesy Car", BY)

    assert (renamed.category.name, renamed.former_names) == ("Courtesy Car", ("Loaner Vehicle",))
    assert renamed.category.description == "No courtesy car."
    assert "Courtesy Car" in setup.names() and "Loaner Vehicle" not in setup.names()
    # What was stored under the old name is found under the new one.
    assert setup.catalog.current_name("Loaner Vehicle") == "Courtesy Car"
    assert setup.catalog.current_name("loaner vehicle") == "Courtesy Car"
    assert setup.catalog.current_name("Cost") == "Cost"
    assert setup.catalog.stored_names("Courtesy Car") == ("Courtesy Car", "Loaner Vehicle")
    assert setup.catalog.stored_names("Cost") == ("Cost",)


def test_a_former_name_cannot_be_given_to_another_category(setup):
    entry = setup.admin.add("Loaner Vehicle", None, BY)
    setup.admin.rename(entry.key, "Courtesy Car", BY)

    # Old complaints under "Loaner Vehicle" would be counted under the wrong one.
    with pytest.raises(CategoryAdminError, match="once had"):
        setup.admin.add("Loaner Vehicle", None, BY)
    other = setup.admin.add("Valet", None, BY)
    with pytest.raises(CategoryAdminError):
        setup.admin.rename(other.key, "loaner vehicle", BY)


def test_a_category_can_go_back_to_a_name_it_had(setup):
    entry = setup.admin.add("Loaner Vehicle", None, BY)
    setup.admin.rename(entry.key, "Courtesy Car", BY)

    back = setup.admin.rename(entry.key, "Loaner Vehicle", BY)

    assert (back.category.name, back.former_names) == ("Loaner Vehicle", ("Courtesy Car",))
    # The same name again changes nothing.
    assert setup.admin.rename(entry.key, "Loaner Vehicle", BY).former_names == ("Courtesy Car",)


def test_a_built_in_category_keeps_its_name(setup):
    with pytest.raises(CategoryAdminError, match="built-in"):
        setup.admin.rename(built_in_key("Cost"), "Pricing", BY)
    with pytest.raises(CategoryAdminError, match="built-in"):
        setup.admin.describe(built_in_key("Cost"), "Anything about money.", BY)


def test_what_counts_as_a_category_can_be_changed(setup):
    entry = setup.admin.add("Loaner Vehicle", "No courtesy car.", BY)

    changed = setup.admin.describe(entry.key, "No car, or a late one.", BY)

    assert changed.category.description == "No car, or a late one."
    assert setup.admin.describe(entry.key, None, BY).category.description is None


# ---- Retire and restore ----


def test_a_retired_category_is_no_longer_reported_and_can_come_back(setup):
    setup.clock[0] = 2000.0

    retired = setup.admin.retire(built_in_key("Hospitality"), BY)

    assert (retired.is_retired, retired.retired_at) == (True, 2000.0)
    assert "Hospitality" not in setup.names()
    # Still listed for the administrator, and still a name nobody else may take.
    assert "Hospitality" in [e.category.name for e in setup.admin.list_categories()]
    with pytest.raises(CategoryAdminError):
        setup.admin.add("Hospitality", None, BY)
    # Retiring again keeps when it was first retired.
    setup.clock[0] = 3000.0
    assert setup.admin.retire(built_in_key("Hospitality"), BY).retired_at == 2000.0

    restored = setup.admin.restore(built_in_key("Hospitality"), BY)

    assert restored.is_retired is False
    # Back in its usual place among the built-ins.
    assert setup.names() == tuple(COMPLAINT_CATEGORIES)


def test_other_cannot_be_retired(setup):
    with pytest.raises(CategoryAdminError, match="cannot be retired"):
        setup.admin.retire(built_in_key("Other"), BY)


def test_an_unknown_category_cannot_be_changed(setup):
    for change in (
        lambda: setup.admin.retire("admin:nope", BY),
        lambda: setup.admin.rename("admin:nope", "X", BY),
        lambda: setup.admin.restore("builtin:Nope", BY),
    ):
        with pytest.raises(CategoryNotFoundError):
            change()


# ---- Accepted themes ----


def test_an_accepted_theme_can_be_renamed_and_retired_too():
    setup = _Setup(themes=[_theme()])
    key = theme_key("t1")
    assert [(e.key, e.source) for e in setup.admin.list_categories() if e.source == "theme"] == [
        (key, "theme")
    ]

    renamed = setup.admin.rename(key, "Courtesy Car", BY)

    assert (renamed.category.name, renamed.former_names) == ("Courtesy Car", ("Loaner Car",))
    # It keeps the theme's own description, and where it came from.
    assert renamed.category.description == "No courtesy car was offered."
    assert renamed.category.candidate_id == "t1"
    assert setup.catalog.current_name("Loaner Car") == "Courtesy Car"

    setup.admin.retire(key, BY)
    assert "Courtesy Car" not in setup.names()


def test_a_theme_cannot_be_accepted_under_a_name_an_added_category_has():
    setup = _Setup()
    setup.admin.add("Loaner Car", None, BY)

    assert setup.catalog.conflicting_name("loaner car", candidate_id="t9") == "Loaner Car"
    assert setup.catalog.conflicting_name("Valet", candidate_id="t9") is None


# ---- The catalog ----


def test_other_instances_see_a_change_within_the_cache_time():
    managed = InMemoryManagedCategoryRepository()
    now = [0.0]
    elsewhere = ComplaintCategoryCatalog(cache_seconds=30.0, clock=lambda: now[0], managed=managed)
    assert elsewhere.names() == tuple(COMPLAINT_CATEGORIES)

    managed.save(ManagedCategory("admin:1", "Valet", "Parking.", updated_at=1.0))
    assert "Valet" not in elsewhere.names()
    now[0] = 31.0
    assert "Valet" in elsewhere.names()


def test_a_store_that_cannot_be_read_keeps_the_last_categories():
    class _Flaky(InMemoryManagedCategoryRepository):
        down = False

        def list_all(self):
            if self.down:
                raise RuntimeError("database is down")
            return super().list_all()

    managed = _Flaky()
    managed.save(ManagedCategory("admin:1", "Valet", updated_at=1.0))
    catalog = ComplaintCategoryCatalog(cache_seconds=0.0, managed=managed)
    assert "Valet" in catalog.names()

    managed.down = True

    assert "Valet" in catalog.names()
    assert catalog.current_name("Valet") == "Valet"


def test_a_category_is_built_in_a_theme_or_an_administrators():
    assert ComplaintCategory("Cost").built_in
    assert not ComplaintCategory("Valet", category_key="admin:1").built_in
    assert not ComplaintCategory("Valet", candidate_id="t1").built_in
    with pytest.raises(ValueError):
        ComplaintCategory("Valet")


# ---- Stored complaints follow a rename ----


class _Calls(ReportSource):
    def __init__(self, *calls: ReportCall) -> None:
        self._calls = calls

    def calls(self, filters, limit):
        return self._calls[:limit]

    def call(self, call_id):
        return next((c for c in self._calls if c.call_id == call_id), None)


def test_reports_count_old_complaints_under_the_categorys_new_name():
    setup = _Setup()
    entry = setup.admin.add("Loaner Vehicle", None, BY)
    setup.admin.rename(entry.key, "Courtesy Car", BY)
    source = RenamingReportSource(
        _Calls(
            ReportCall("old", 10.0, complaints=(ReportComplaint("Loaner Vehicle", "detected"),)),
            ReportCall("new", 20.0, complaints=(ReportComplaint("Courtesy Car", "resolved"),)),
            # Raised under both names while the rename happened: one complaint.
            ReportCall(
                "both",
                30.0,
                complaints=(
                    ReportComplaint("Loaner Vehicle", "detected"),
                    ReportComplaint("Courtesy Car", "probed"),
                    ReportComplaint("Cost", "detected"),
                ),
            ),
            ReportCall("plain", 40.0, complaints=(ReportComplaint("Cost", "detected"),)),
        ),
        setup.catalog.current_name,
    )

    report = ReportService(source).complaint_report(ReportFilters(0.0, 86400.0))

    assert {total.category: total.complaints for total in report.categories} == {
        "Courtesy Car": 3,
        "Cost": 2,
    }
    assert [c.category for c in source.call("both").complaints] == ["Courtesy Car", "Cost"]
    assert source.call("both").complaints[0].status == "detected"  # the first stands
    assert source.call("nope") is None
    # The category filter is by the name it has now.
    filtered = ReportService(source).complaint_report(
        ReportFilters(0.0, 86400.0, category="Courtesy Car")
    )
    assert filtered.total_complaints == 3


# ---- The API ----


class _Complaints(ComplaintDetectionProvider):
    def __init__(self) -> None:
        self.category = "Loaner Vehicle"

    def detect(self, conversation, learning_context=()):
        return [ComplaintDetectionResult(self.category, 0.9, "No car was offered.", lines=(1,))]


class _Calm(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEUTRAL, 0.7, "Calm.")


class _NoQuestions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


def _api():
    services = build_api_services(
        _Complaints(), _Calm(), _NoQuestions(), Settings(_env_file=None)  # type: ignore[call-arg]
    )
    client = TestClient(create_app(services))

    def sign_in(user_id: str, role: UserRole) -> dict[str, str]:
        user = User(user_id, f"{user_id}@example.com", "hash", role, True, time.time())
        services.user_repository.save(user)
        return {"Authorization": f"Bearer {create_access_token(user)}"}

    return client, sign_in


URL = "/api/v1/admin/complaint-categories"


def test_an_administrator_manages_the_categories_through_the_api():
    client, sign_in = _api()
    admin = sign_in("adm", UserRole.ADMIN)

    listed = client.get(URL, headers=admin).json()
    assert [c["name"] for c in listed] == list(COMPLAINT_CATEGORIES)
    cost, other = listed[0], listed[-1]
    assert (cost["key"], cost["source"], cost["can_rename"], cost["can_retire"]) == (
        "builtin:Cost",
        "built_in",
        False,
        True,
    )
    assert (other["can_rename"], other["can_retire"]) == (False, False)

    created = client.post(
        URL, json={"name": "Loaner Vehicle", "description": "No courtesy car."}, headers=admin
    )
    assert created.status_code == 201
    key = created.json()["key"]
    assert (created.json()["source"], created.json()["can_rename"]) == ("admin", True)
    # Everyone's category list (filters, the detector) has it.
    names = [c["name"] for c in client.get("/api/v1/complaints/categories", headers=admin).json()]
    assert "Loaner Vehicle" in names

    renamed = client.patch(f"{URL}/{key}", json={"name": "Courtesy Car"}, headers=admin).json()
    assert (renamed["name"], renamed["former_names"]) == ("Courtesy Car", ["Loaner Vehicle"])
    retired = client.patch(f"{URL}/{key}", json={"retired": True}, headers=admin).json()
    assert retired["retired_at"] is not None
    assert client.patch(f"{URL}/{key}", json={"retired": False}, headers=admin).json()[
        "retired_at"
    ] is None
    described = client.patch(f"{URL}/{key}", json={"description": None}, headers=admin).json()
    assert described["description"] is None

    assert client.post(URL, json={"name": "cost"}, headers=admin).status_code == 409
    assert client.patch(f"{URL}/builtin:Cost", json={"name": "Pricing"}, headers=admin).status_code == 409
    assert client.patch(f"{URL}/builtin:Other", json={"retired": True}, headers=admin).status_code == 409
    assert client.patch(f"{URL}/admin:nope", json={"retired": True}, headers=admin).status_code == 404
    assert client.patch(f"{URL}/{key}", json={}, headers=admin).status_code == 422
    assert client.post(URL, json={"name": "x" * 41}, headers=admin).status_code == 422
    retire_hospitality = client.patch(
        f"{URL}/builtin:Hospitality", json={"retired": True}, headers=admin
    )
    assert retire_hospitality.status_code == 200


def test_only_administrators_manage_the_categories():
    client, sign_in = _api()

    for role in (UserRole.ICR, UserRole.SUPERVISOR):
        headers = sign_in(role.value.lower(), role)
        assert client.get(URL, headers=headers).status_code == 403
        assert client.post(URL, json={"name": "Valet"}, headers=headers).status_code == 403
        assert client.patch(f"{URL}/builtin:Cost", json={"retired": True}, headers=headers).status_code == 403
    assert client.get(URL).status_code == 401


def test_a_calls_own_pages_show_old_complaints_under_the_new_name():
    client, sign_in = _api()
    admin, asha = sign_in("adm", UserRole.ADMIN), sign_in("asha", UserRole.ICR)
    key = client.post(URL, json={"name": "Loaner Vehicle"}, headers=admin).json()["key"]
    client.post("/api/v1/calls", json={"call_id": "c1", "start_time": None}, headers=asha)
    line = {
        "utterance_id": "u1",
        "transcript": "Nobody offered me a car.",
        "speaker_role": "CUSTOMER",
        "languages": ["en"],
        "start_time": 0.0,
        "end_time": 1.0,
    }
    said = client.post("/api/v1/calls/c1/utterances", json=line, headers=asha).json()
    assert [c["category"] for c in said["coverage"]["complaints"]] == ["Loaner Vehicle"]

    client.patch(f"{URL}/{key}", json={"name": "Courtesy Car"}, headers=admin)

    analysis = client.get("/api/v1/calls/c1/analysis", headers=asha).json()
    assert [c["category"] for c in analysis["coverage"]["complaints"]] == ["Courtesy Car"]
    call = client.get("/api/v1/calls/c1", headers=asha).json()
    assert call["utterances"][0]["complaint_categories"] == ["Courtesy Car"]
    supervisor = sign_in("sup", UserRole.SUPERVISOR)
    live = client.get("/api/v1/live-calls", headers=supervisor).json()
    assert [c["category"] for c in live["items"][0]["complaints"]] == ["Courtesy Car"]
    # The Complaints page, and its filter by the new name.
    listed = client.get("/api/v1/complaints", headers=asha).json()
    assert [c["category"] for c in listed] == ["Courtesy Car"]
    by_new_name = client.get(
        "/api/v1/complaints", params={"category": "Courtesy Car"}, headers=asha
    ).json()
    assert len(by_new_name) == 1
    report = client.get("/api/v1/reports/complaints", headers=supervisor).json()
    assert [c["category"] for c in report["categories"]] == ["Courtesy Car"]
