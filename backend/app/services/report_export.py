"""A complaint report as a file: CSV (the complaints, one per row), Excel
(the same plus a sheet per section) or PDF (the sections, to print).

What it carries follows the layout an administrator has set (see
report_layout): the company name and title, which sections and in what
order, and which columns the list of complaints has.
"""

import csv
import io
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from app.services.performance import Figures, PerformanceReport
from app.services.pdf_text import LEFT_OUT_NOTE, PdfText
from app.services.report_layout import COLUMNS, DEFAULT_LAYOUT, ReportLayout
from app.services.reporting import Report

EXPORT_FORMATS = ("csv", "xlsx", "pdf")
_MEDIA_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
_DIRECTIONS = {"inbound": "Incoming", "outbound": "Outgoing"}
# The PDF's tables keep to what fits a page width.
_PDF_MAX_TREND_COLUMNS = 16
_PDF_MAX_LOCATION_COLUMNS = 10
# Spreadsheets run a cell that starts with one of these as a formula.
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def export_report(
    report: Report, file_format: str, layout: ReportLayout = DEFAULT_LAYOUT
) -> tuple[bytes, str, str]:
    """(content, media type, filename)."""
    if file_format not in EXPORT_FORMATS:
        raise ValueError(f"Unsupported export format: {file_format!r}.")
    content = {"csv": _csv, "xlsx": _xlsx, "pdf": _pdf}[file_format](report, layout)
    day = _local(report, report.filters.started_from).strftime("%Y-%m-%d")
    return content, _MEDIA_TYPES[file_format], f"complaint-report-{day}.{file_format}"


_SCORECARD_COLUMNS = (
    "Executive",
    "Calls",
    "Complaints",
    "Complaints asked about",
    "Coverage score % (estimate)",
    "First Call Resolution % (estimate)",
    "Calls FCR is judged on",
    "Repeat complaints % (estimate)",
    "CSAT estimate (1-5)",
    "Calls ending negative or worse",
    "Churn risk high",
    "Churn risk medium",
    "Churn risk low",
    "High or critical escalations",
    "Suggested questions accepted",
    "Suggested questions skipped",
    "Audit score 0-100 (estimate)",
    "Calls audited",
    "Weakest category",
    "Weakest category score",
)


def _percent(rate: float | None) -> float | str:
    return "" if rate is None else round(rate * 100, 1)


def _rate(part: int, whole: int) -> float | None:
    return None if whole == 0 else part / whole


def _scorecard_row(name: str, figures: Figures) -> list:
    return [
        name,
        figures.calls,
        figures.complaints,
        figures.probed_complaints,
        _percent(figures.coverage_score),
        _percent(figures.fcr_rate),
        figures.fcr_calls,
        _percent(figures.repeat_rate),
        "" if figures.csat is None else figures.csat,
        figures.negative_calls,
        figures.churn_high,
        figures.churn_medium,
        figures.churn_low,
        figures.serious_escalations,
        figures.questions_accepted,
        figures.questions_skipped,
        "" if figures.audit_score is None else figures.audit_score,
        figures.audited_calls,
        figures.weakest_category or "",
        "" if figures.weakest_category_score is None else figures.weakest_category_score,
    ]


def export_scorecard(
    report: PerformanceReport, file_format: str, tz_offset_minutes: int = 0
) -> tuple[bytes, str, str]:
    """The executives' scorecard as (content, media type, filename): a row
    per executive and one for everyone together."""
    if file_format not in ("csv", "xlsx"):
        raise ValueError(f"Unsupported export format: {file_format!r}.")
    rows = [_scorecard_row(e.name, e.figures) for e in report.executives]
    rows.append(_scorecard_row("All executives", report.overall))
    zone = timezone(timedelta(minutes=tz_offset_minutes))
    day = datetime.fromtimestamp(report.filters.started_from, zone).strftime("%Y-%m-%d")
    if file_format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(_SCORECARD_COLUMNS)
        for row in rows:
            writer.writerow([_safe(cell) for cell in row])
        content = buffer.getvalue().encode("utf-8-sig")
    else:
        workbook = Workbook()
        workbook.remove(workbook.active)
        _sheet(workbook, "Scorecard", list(_SCORECARD_COLUMNS), rows)
        prefix = "Week of " if report.bucket == "week" else ""
        periods = [
            f"{prefix}{datetime.fromtimestamp(at, zone):%d %b %Y}" for at in report.bucket_starts
        ]
        _sheet(
            workbook,
            "Tone trend",
            ["Executive (% of calls ending negative or worse)"] + periods,
            [
                [name] + [_percent(_rate(point.negative, point.rated)) for point in trend]
                for name, trend in (
                    *((e.name, e.tone_trend) for e in report.executives),
                    ("All executives", report.tone_trend),
                )
            ],
        )
        out = io.BytesIO()
        workbook.save(out)
        content = out.getvalue()
    return content, _MEDIA_TYPES[file_format], f"executive-scorecard-{day}.{file_format}"


# ---- Shared ----


def _local(report: Report, at: float) -> datetime:
    """The moment by the reader's clock."""
    zone = timezone(timedelta(minutes=report.tz_offset_minutes))
    return datetime.fromtimestamp(at, zone)


def _bucket_labels(report: Report) -> list[str]:
    prefix = "Week of " if report.bucket == "week" else ""
    return [f"{prefix}{_local(report, at):%d %b %Y}" for at in report.bucket_starts]


def _filter_lines(report: Report) -> list[tuple[str, str]]:
    filters = report.filters
    # The range's end is exclusive: its last day is the one before.
    last_day = _local(report, filters.started_to - 1)
    lines = [
        ("Calls from", f"{_local(report, filters.started_from):%d %b %Y}"),
        ("Calls to", f"{last_day:%d %b %Y}"),
        ("Location", report.location_name or ("All" if filters.location_id is None else "?")),
        (
            "Executive",
            report.executive_name or ("All" if filters.executive_user_id is None else "?"),
        ),
        ("Category", filters.category or "All"),
        ("Tone", "All" if filters.sentiment is None else filters.sentiment.value.capitalize()),
        (
            "Direction",
            "All" if filters.direction is None else _DIRECTIONS[filters.direction.value],
        ),
    ]
    return lines


def _total_lines(report: Report) -> list[tuple[str, int]]:
    return [
        ("Calls", report.total_calls),
        ("Calls with a complaint", report.calls_with_complaints),
        ("Complaints", report.total_complaints),
    ]


def _complaint_header(layout: ReportLayout) -> list[str]:
    return [COLUMNS[column] for column in layout.columns]


def _complaint_rows(report: Report, layout: ReportLayout) -> list[list[str]]:
    """The list of complaints, with the layout's columns in its order."""
    rows = []
    for row in report.rows:
        cells = {
            "call_id": row.call_id,
            "call_date": f"{_local(report, row.start_time):%Y-%m-%d %H:%M}",
            "location": row.location_name or "",
            "executive": row.executive_name or "",
            "direction": "" if row.direction is None else _DIRECTIONS[row.direction.value],
            "tone": "" if row.sentiment is None else row.sentiment.value.capitalize(),
            "category": row.category,
            "status": row.status.replace("_", " "),
            "description": row.description or "",
            "customer_words": row.quote or "",
        }
        rows.append([cells[column] for column in layout.columns])
    return rows


def _tone_rows(report: Report) -> list[list]:
    tone = report.tone
    return [
        *([count.label.value.capitalize(), count.calls] for count in tone.by_tone),
        ["Calls with a tone", tone.rated_calls],
        ["Ending negative or worse", tone.negative_calls],
        ["Calls whose lines carry tones", tone.tracked_calls],
        ["Customer ended milder than they began", tone.improved_calls],
        ["Customer ended harsher than they began", tone.worsened_calls],
    ]


def _tone_trend_rows(report: Report) -> list[list]:
    trend = report.tone.trend
    return [
        ["Calls with a tone", *(point.rated for point in trend)],
        ["Ending negative or worse", *(point.negative for point in trend)],
        [
            "% negative or worse",
            *(_percent(_rate(point.negative, point.rated)) for point in trend),
        ],
    ]


def _safe(value):
    """Text that a spreadsheet will show rather than run."""
    if isinstance(value, str) and value.startswith(_FORMULA_STARTS):
        return "'" + value
    return value


# ---- CSV ----


def _csv(report: Report, layout: ReportLayout = DEFAULT_LAYOUT) -> bytes:
    """The list of complaints and nothing else: a file for other programs."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(_complaint_header(layout))
    for row in _complaint_rows(report, layout):
        writer.writerow([_safe(cell) for cell in row])
    # With a byte-order mark, so Excel reads it as UTF-8.
    return buffer.getvalue().encode("utf-8-sig")


# ---- Excel ----


def _sheet(workbook: Workbook, title: str, header: list[str], rows: list[list]) -> None:
    sheet = workbook.create_sheet(title)
    sheet.append(header)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append([_safe(cell) for cell in row])
    sheet.freeze_panes = "A2"
    for index, name in enumerate(header, start=1):
        longest = max([len(str(name))] + [len(str(row[index - 1])) for row in rows[:200]])
        sheet.column_dimensions[get_column_letter(index)].width = min(60, max(10, longest + 2))


def _xlsx(report: Report, layout: ReportLayout = DEFAULT_LAYOUT) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)

    # Always there: what the report is of. The sections follow as sheets,
    # in the layout's order.
    summary = [[name, value] for name, value in _filter_lines(report)]
    summary += [["", ""]] + [[name, value] for name, value in _total_lines(report)]
    if layout.has("categories"):
        summary += [["", ""], ["Category", "Complaints", "Resolved"]]
        summary += [[c.category, c.complaints, c.resolved] for c in report.categories]
    _sheet(workbook, "Summary", [layout.title, layout.company_name], summary)

    def trend() -> None:
        _sheet(
            workbook,
            "Trend",
            ["Category"] + _bucket_labels(report),
            [[series.category, *series.counts] for series in report.trend],
        )

    def locations() -> None:
        _sheet(
            workbook,
            "By location",
            ["Category"] + [location.name for location in report.locations],
            [[row.category, *row.counts] for row in report.heatmap],
        )

    def root_causes() -> None:
        _sheet(
            workbook,
            "Root causes",
            [
                "Category",
                "What the complaints say (similar wording grouped)",
                "In a customer's words",
                "Complaints",
                "Calls",
            ],
            [
                [
                    cause.category,
                    theme.text,
                    theme.quote or "",
                    theme.complaints,
                    ", ".join(theme.call_ids),
                ]
                for cause in report.root_causes
                for theme in cause.themes
            ],
        )

    def tone() -> None:
        _sheet(workbook, "Tone", ["How calls ended", "Calls"], _tone_rows(report))

    def tone_trend() -> None:
        _sheet(workbook, "Tone trend", ["", *_bucket_labels(report)], _tone_trend_rows(report))

    def complaints() -> None:
        _sheet(
            workbook, "Complaints", _complaint_header(layout), _complaint_rows(report, layout)
        )

    sheets = {
        "trend": trend,
        "locations": locations,
        "root_causes": root_causes,
        "tone": tone,
        "tone_trend": tone_trend,
        "complaints": complaints,
    }
    for name in layout.sections:
        if name in sheets:
            sheets[name]()

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# ---- PDF ----


def _pdf(report: Report, layout: ReportLayout = DEFAULT_LAYOUT) -> bytes:
    # Imported here: only this export needs the PDF library.
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    small = styles["BodyText"].clone("small", fontSize=8, leading=10)

    # Tamil, Telugu, Kannada and Malayalam are printed in their own fonts.
    writer = PdfText()

    def text(value, style=small) -> Paragraph:
        return writer.paragraph(value, style)

    def table(rows: list[list], widths: list[float] | None = None) -> Table:
        made = Table([[text(cell) for cell in row] for row in rows], colWidths=widths, repeatRows=1)
        made.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9f0f7")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c5d0dc")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return made

    story: list = []
    if layout.company_name:
        story.append(text(layout.company_name, styles["Heading3"]))
    title_at = len(story)
    story.append(text(layout.title, styles["Title"]))
    story.append(
        text(
            " · ".join(f"{name}: {value}" for name, value in _filter_lines(report)),
            body,
        )
    )
    story.append(
        text(" · ".join(f"{name}: {value}" for name, value in _total_lines(report)), body)
    )

    def section(title: str) -> None:
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph(escape(title), styles["Heading2"]))

    def periods(labels: list[str]) -> tuple[slice, str]:
        """The most recent periods, when there are more than fit the page,
        and what to say about that."""
        shown = slice(max(0, len(labels) - _PDF_MAX_TREND_COLUMNS), len(labels))
        note = (
            f" (last {_PDF_MAX_TREND_COLUMNS} of {len(labels)}; all are in the Excel export)"
            if len(labels) > _PDF_MAX_TREND_COLUMNS
            else ""
        )
        return shown, note

    def categories() -> None:
        section("Complaints by category")
        story.append(
            table(
                [["Category", "Complaints", "Resolved"]]
                + [[c.category, c.complaints, c.resolved] for c in report.categories],
                [90 * mm, 35 * mm, 45 * mm],
            )
        )

    def trend() -> None:
        labels = _bucket_labels(report)
        shown, note = periods(labels)
        section("Trend by " + report.bucket + note)
        story.append(
            table(
                [["Category"] + [label.replace("Week of ", "") for label in labels[shown]]]
                + [[series.category, *series.counts[shown]] for series in report.trend]
            )
        )

    def locations() -> None:
        places = report.locations[:_PDF_MAX_LOCATION_COLUMNS]
        section(
            "Category by location"
            + (
                f" (first {len(places)} of {len(report.locations)} locations)"
                if len(report.locations) > len(places)
                else ""
            )
        )
        story.append(
            table(
                [["Category"] + [location.name for location in places]]
                + [[row.category, *row.counts[: len(places)]] for row in report.heatmap]
            )
        )

    def root_causes() -> None:
        section("Root causes (complaints in similar words, grouped by a fixed rule)")
        for cause in report.root_causes:
            story.append(
                text(
                    f"{cause.category}: {cause.complaints} complaints, "
                    f"{cause.resolved} resolved"
                    + (f", {cause.undescribed} not described in a call summary" if cause.undescribed else ""),
                    body,
                )
            )
            if cause.themes:
                story.append(
                    table(
                        [["What the complaints say", "Complaints"]]
                        + [[theme.text, theme.complaints] for theme in cause.themes],
                        [215 * mm, 30 * mm],
                    )
                )
            story.append(Spacer(1, 2 * mm))

    def tone() -> None:
        section("Tone: how calls ended")
        story.append(
            table([["How calls ended", "Calls"]] + _tone_rows(report), [110 * mm, 35 * mm])
        )

    def tone_trend() -> None:
        labels = _bucket_labels(report)
        shown, note = periods(labels)
        section("Tone trend by " + report.bucket + note)
        story.append(
            table(
                [[""] + [label.replace("Week of ", "") for label in labels[shown]]]
                + [[row[0], *row[1:][shown]] for row in _tone_trend_rows(report)]
            )
        )

    sections = {
        "categories": categories,
        "trend": trend,
        "locations": locations,
        "root_causes": root_causes,
        "tone": tone,
        "tone_trend": tone_trend,
    }
    if not report.categories:
        story.append(Spacer(1, 5 * mm))
        story.append(text("No complaints match these filters.", body))
    else:
        # The list of complaints is too wide to print: Excel and CSV have it.
        for name in layout.sections:
            if name in sections:
                sections[name]()

    if writer.left_out:
        # Under the title, where it is read before the tables.
        story.insert(title_at + 1, Paragraph(escape(LEFT_OUT_NOTE), body))

    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=layout.title,
    ).build(story)
    return buffer.getvalue()
