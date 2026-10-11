"""The layout of exported reports, as an administrator sets it: the company
name and title, which sections and in what order, which columns the list
of complaints has; what is refused; storage; and who may change it."""

import csv
import io
import time

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.ai.complaint.provider import ComplaintDetectionProvider, ComplaintDetectionResult
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentLabel, SentimentResult
from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.core.config import Settings
from app.domain.user import User, UserRole
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import build_session_factory
from app.infrastructure.database.repositories.report_layout_repository import (
    PostgresReportLayoutRepository,
)
from app.security.jwt import create_access_token
from app.services.audit_log import AuditFilter
from app.services.report_export import export_report
from app.services.report_layout import (
    COLUMNS,
    DEFAULT_LAYOUT,
    SECTIONS,
    InMemoryReportLayoutRepository,
    ReportLayout,
    ReportLayoutError,
    ReportLayoutService,
    layout_from_stored,
    validated,
)
from tests.test_reports import stores  # noqa: F401  (the report fixtures)


def _sheets(report, layout) -> list[str]:
    content, _, _ = export_report(report, "xlsx", layout)
    return load_workbook(io.BytesIO(content)).sheetnames


def _csv_rows(report, layout) -> list[list[str]]:
    content, _, _ = export_report(report, "csv", layout)
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))


# ---- What a layout may be ----


def test_the_built_in_layout_has_every_section_and_column_in_order():
    assert DEFAULT_LAYOUT.title == "Complaint report"
    assert DEFAULT_LAYOUT.company_name == ""
    assert DEFAULT_LAYOUT.sections == tuple(SECTIONS)
    assert DEFAULT_LAYOUT.columns == tuple(COLUMNS)


def test_a_layout_is_tidied_and_keeps_the_order_given():
    layout = validated("  Sri  Murugan Motors ", " Monthly   complaints ", ["tone", "categories"], ["category", "call_id"])

    assert (layout.company_name, layout.title) == ("Sri Murugan Motors", "Monthly complaints")
    assert layout.sections == ("tone", "categories")
    assert layout.columns == ("category", "call_id")
    assert layout.has("tone") and not layout.has("trend")


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (("", " ", ["tone"], ["category"]), "The report needs a title."),
        (("", "x" * 101, ["tone"], ["category"]), "at most 100 characters"),
        (("y" * 101, "Title", ["tone"], ["category"]), "at most 100 characters"),
        (("", "Title", ["tone", "weather"], ["category"]), "Unknown section: weather."),
        (("", "Title", ["tone"], ["category", "phone"]), "Unknown column: phone."),
        (("", "Title", ["tone", "tone"], ["category"]), "A section is listed twice."),
        (("", "Title", ["tone"], ["category", "category"]), "A column is listed twice."),
        (("", "Title", [], ["category"]), "at least one section"),
        (("", "Title", ["tone"], []), "at least one column"),
    ],
)
def test_a_layout_that_cannot_be_used_is_refused(values, message):
    with pytest.raises(ReportLayoutError, match=message):
        validated(*values)


def test_a_stored_layout_naming_things_that_no_longer_exist_still_works():
    layout = layout_from_stored(
        {"title": "Old", "sections": ["weather", "tone"], "columns": ["phone"], "company_name": None}
    )

    assert (layout.title, layout.company_name) == ("Old", "")
    assert layout.sections == ("tone",)
    # No known column left: the built-in ones, rather than an empty list.
    assert layout.columns == DEFAULT_LAYOUT.columns


# ---- What the exports do with it ----


def test_the_excel_file_has_the_chosen_sections_as_sheets_in_the_chosen_order(stores):  # noqa: F811
    report = stores.report()

    assert _sheets(report, DEFAULT_LAYOUT) == [
        "Summary", "Trend", "By location", "Root causes", "Tone", "Tone trend", "Complaints",
    ]
    chosen = ReportLayout(sections=("complaints", "tone", "trend"))
    assert _sheets(report, chosen) == ["Summary", "Complaints", "Tone", "Trend"]
    assert _sheets(report, ReportLayout(sections=("categories",))) == ["Summary"]


def test_the_summary_sheet_carries_the_title_the_company_and_the_categories_only_when_chosen(stores):  # noqa: F811
    report = stores.report()

    def summary(layout) -> list[tuple]:
        content, _, _ = export_report(report, "xlsx", layout)
        return [row for row in load_workbook(io.BytesIO(content))["Summary"].iter_rows(values_only=True)]

    named = summary(ReportLayout(company_name="Sri Murugan Motors", title="Monthly complaints"))
    assert named[0][:2] == ("Monthly complaints", "Sri Murugan Motors")
    assert ("Category", "Complaints", "Resolved") in [row[:3] for row in named]
    without = summary(ReportLayout(sections=("tone",)))
    assert ("Category", "Complaints", "Resolved") not in [row[:3] for row in without]
    assert "Complaints" in [row[0] for row in without]  # the totals stay


def test_the_list_of_complaints_has_the_chosen_columns_in_the_chosen_order(stores):  # noqa: F811
    report = stores.report()
    full = _csv_rows(report, DEFAULT_LAYOUT)
    chosen = _csv_rows(report, ReportLayout(columns=("category", "call_id", "status")))

    assert full[0] == list(COLUMNS.values())
    assert chosen[0] == ["Category", "Call ID", "Status"]
    assert len(chosen) == len(full)
    assert [row for row in chosen[1:]] == [[row[6], row[0], row[7]] for row in full[1:]]

    content, _, _ = export_report(report, "xlsx", ReportLayout(columns=("category", "call_id")))
    sheet = load_workbook(io.BytesIO(content))["Complaints"]
    assert [cell.value for cell in sheet[1]] == ["Category", "Call ID"]


def test_the_pdf_prints_the_company_and_title_and_only_the_chosen_sections(stores, monkeypatch):  # noqa: F811
    from app.services import report_export

    printed: list[str] = []

    class _Recording(report_export.PdfText):
        def paragraph(self, value, style):
            printed.append(str(value))
            return super().paragraph(value, style)

    monkeypatch.setattr(report_export, "PdfText", _Recording)
    report = stores.report()

    content, _, _ = export_report(
        report, "pdf", ReportLayout("Sri Murugan Motors", "Monthly complaints", ("tone", "categories"))
    )

    assert content[:5] == b"%PDF-"
    assert printed[:2] == ["Sri Murugan Motors", "Monthly complaints"]
    assert "How calls ended" in printed
    assert "Resolved" in printed  # the categories table
    assert printed.index("How calls ended") < printed.index("Resolved")  # in the order chosen
    assert not any("What the complaints say" in text for text in printed)  # root causes left out

    printed.clear()
    export_report(report, "pdf", DEFAULT_LAYOUT)
    assert printed[0] == "Complaint report"  # no company line when none is set
    assert any("What the complaints say" in text for text in printed)


def test_a_layout_with_only_the_list_of_complaints_still_makes_a_pdf(stores):  # noqa: F811
    content, _, _ = export_report(stores.report(), "pdf", ReportLayout(sections=("complaints",)))

    assert content[:5] == b"%PDF-"


# ---- Keeping it ----


@pytest.fixture(params=["memory", "sql"])
def repository(request):
    if request.param == "memory":
        return InMemoryReportLayoutRepository()
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    request.addfinalizer(engine.dispose)
    return PostgresReportLayoutRepository(build_session_factory(engine))


def test_a_saved_layout_is_kept_with_who_saved_it_and_when(repository):
    service = ReportLayoutService(repository, clock=lambda: 5000.0)
    assert service.saved() is None
    assert service.layout() == DEFAULT_LAYOUT

    service.save("Sri Murugan Motors", "Monthly complaints", ["tone", "trend"], ["category"], "admin-1")
    service.save("Sri Murugan Motors", "Weekly complaints", ["trend"], ["category", "status"], "admin-2")

    fresh = ReportLayoutService(repository)  # another server
    saved = fresh.saved()
    assert saved.layout == ReportLayout(
        "Sri Murugan Motors", "Weekly complaints", ("trend",), ("category", "status")
    )
    assert (saved.updated_at, saved.updated_by) == (5000.0, "admin-2")


def test_another_servers_change_is_seen_once_the_short_cache_runs_out(repository):
    now = [0.0]
    here = ReportLayoutService(repository, cache_seconds=30, monotonic=lambda: now[0])
    there = ReportLayoutService(repository)
    assert here.layout() == DEFAULT_LAYOUT

    there.save("", "Changed elsewhere", ["tone"], ["category"], "admin-1")
    assert here.layout().title == "Complaint report"  # still cached
    now[0] = 31.0
    assert here.layout().title == "Changed elsewhere"


def test_a_refused_layout_changes_nothing(repository):
    service = ReportLayoutService(repository)
    service.save("", "Kept", ["tone"], ["category"], "admin-1")

    with pytest.raises(ReportLayoutError):
        service.save("", "", ["tone"], ["category"], "admin-1")

    assert service.layout().title == "Kept"


# ---- Through the application ----


class _Complaints(ComplaintDetectionProvider):
    def detect(self, conversation, learning_context=()):
        return [ComplaintDetectionResult("Cost", 0.9, "The bill was too high.")]


class _Calm(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEUTRAL, 0.7, "Calm.")


class _NoQuestions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


class _Api:
    def __init__(self) -> None:
        self.services = build_api_services(
            _Complaints(), _Calm(), _NoQuestions(), Settings(_env_file=None)  # type: ignore[call-arg]
        )
        self.client = TestClient(create_app(self.services))

    def user(self, user_id: str, role: UserRole) -> dict[str, str]:
        user = User(user_id, f"{user_id}@example.com", "hash", role, True, time.time())
        self.services.user_repository.save(user)
        return {"Authorization": f"Bearer {create_access_token(user)}"}


URL = "/api/v1/admin/report-layout"
LAYOUT = {
    "company_name": "Sri Murugan Motors",
    "title": "Monthly complaints",
    "sections": ["complaints", "tone"],
    "columns": ["category", "call_id"],
}


def test_an_admin_reads_the_layout_and_what_can_be_chosen():
    api = _Api()

    body = api.client.get(URL, headers=api.user("admin-1", UserRole.ADMIN)).json()

    assert (body["title"], body["company_name"]) == ("Complaint report", "")
    assert body["sections"] == list(SECTIONS)
    assert body["columns"] == list(COLUMNS)
    assert (body["updated_at"], body["updated_by"]) == (None, None)
    assert {"id": "complaints", "name": "List of complaints", "in_pdf": False} in body["available_sections"]
    assert {"id": "tone", "name": "Tone", "in_pdf": True} in body["available_sections"]
    assert [c["name"] for c in body["available_columns"]] == list(COLUMNS.values())


def test_a_saved_layout_is_what_the_next_download_follows():
    api = _Api()
    admin = api.user("admin-1", UserRole.ADMIN)
    supervisor = api.user("sup-1", UserRole.SUPERVISOR)
    now = time.time()
    api.client.post("/api/v1/calls", json={"call_id": "c1", "start_time": None}, headers=supervisor)
    api.client.post(
        "/api/v1/calls/c1/utterances",
        json={"utterance_id": "c1-u1", "transcript": "The bill was too high.", "speaker_role": "CUSTOMER",
              "languages": ["en"], "start_time": 0.0, "end_time": 2.0},
        headers=supervisor,
    )
    params = {"started_from": now - 3600, "started_to": now + 3600}

    saved = api.client.put(URL, json=LAYOUT, headers=admin)

    assert saved.status_code == 200
    assert saved.json()["updated_by"] == "admin-1"
    assert saved.json()["sections"] == ["complaints", "tone"]
    excel = api.client.get("/api/v1/reports/complaints/export", params={**params, "format": "xlsx"}, headers=supervisor)
    workbook = load_workbook(io.BytesIO(excel.content))
    assert workbook.sheetnames == ["Summary", "Complaints", "Tone"]
    assert workbook["Summary"]["A1"].value == "Monthly complaints"
    assert workbook["Summary"]["B1"].value == "Sri Murugan Motors"
    listed = api.client.get("/api/v1/reports/complaints/export", params={**params, "format": "csv"}, headers=supervisor)
    rows = list(csv.reader(io.StringIO(listed.content.decode("utf-8-sig"))))
    assert rows == [["Category", "Call ID"], ["Cost", "c1"]]


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"sections": ["weather"]}, "Unknown section: weather."),
        ({"columns": ["category", "category"]}, "A column is listed twice."),
        ({"title": "   "}, "The report needs a title."),
    ],
)
def test_a_layout_that_cannot_be_used_is_refused_with_the_reason(change, detail):
    api = _Api()
    admin = api.user("admin-1", UserRole.ADMIN)

    response = api.client.put(URL, json={**LAYOUT, **change}, headers=admin)

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    assert api.client.get(URL, headers=admin).json()["title"] == "Complaint report"


@pytest.mark.parametrize("role", [UserRole.ICR, UserRole.SUPERVISOR, UserRole.MANAGEMENT])
def test_only_admins_see_or_change_the_layout(role):
    api = _Api()
    headers = api.user("someone", role)

    assert api.client.get(URL, headers=headers).status_code == 403
    assert api.client.put(URL, json=LAYOUT, headers=headers).status_code == 403
    assert api.services.report_layout.saved() is None


def test_changing_the_layout_is_in_the_audit_log():
    api = _Api()

    api.client.put(URL, json=LAYOUT, headers=api.user("admin-1", UserRole.ADMIN))
    api.services.audit_log.flush()

    (entry,) = api.services.audit_log.search(AuditFilter(action="save_report_layout")).entries
    assert (entry.user_id, entry.method, entry.status_code) == ("admin-1", "PUT", 200)
