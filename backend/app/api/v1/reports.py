import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict

from app.ai.sentiment.provider import SentimentLabel
from app.api.dependencies import get_performance_service, get_report_service
from app.api.security_dependencies import require_roles
from app.domain.conversation import CallDirection
from app.domain.user import User, UserRole
from app.services.performance import PerformanceService
from app.services.report_export import export_report, export_scorecard
from app.services.reporting import SECONDS_PER_DAY, Report, ReportFilters, ReportService

router = APIRouter(prefix="/reports", tags=["reports"])

_SUPERVISORS = require_roles(UserRole.SUPERVISOR, UserRole.ADMIN)
DEFAULT_RANGE_DAYS = 30
# UTC-12:00 to UTC+14:00.
_MIN_TZ_OFFSET, _MAX_TZ_OFFSET = -720, 840


class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ReportFiltersResponse(_Response):
    started_from: float
    started_to: float
    location_id: str | None
    executive_user_id: str | None
    direction: CallDirection | None
    sentiment: SentimentLabel | None
    category: str | None


class CategoryTotalResponse(_Response):
    category: str
    complaints: int
    resolved: int


class TrendSeriesResponse(_Response):
    category: str
    counts: list[int]


class TonePointResponse(_Response):
    # Calls with a tone, and those ending negative or worse.
    rated: int
    negative: int


class ToneCountResponse(_Response):
    label: SentimentLabel
    calls: int


class ToneSummaryResponse(_Response):
    rated_calls: int
    # By the tone the call ended on, mildest first.
    by_tone: list[ToneCountResponse]
    negative_calls: int
    # Calls whose lines carry tones, and those whose customer ended in a
    # milder, or a harsher, tone than they began.
    tracked_calls: int
    improved_calls: int
    worsened_calls: int
    # One per bucket_starts entry.
    trend: list[TonePointResponse]


class HeatmapLocationResponse(_Response):
    location_id: str | None
    name: str


class HeatmapRowResponse(_Response):
    category: str
    counts: list[int]


class ThemeResponse(_Response):
    text: str
    # The customer's own words on one of the calls; null when not known.
    quote: str | None = None
    complaints: int
    call_ids: list[str]


class RootCauseResponse(_Response):
    category: str
    complaints: int
    resolved: int
    undescribed: int
    themes: list[ThemeResponse]


class ComplaintReportResponse(_Response):
    filters: ReportFiltersResponse
    bucket: Literal["day", "week"]
    tz_offset_minutes: int
    total_calls: int
    calls_with_complaints: int
    total_complaints: int
    # Most frequent first; every per-category list below is in this order.
    categories: list[CategoryTotalResponse]
    # When each day or week starts (epoch seconds); one per trend count.
    bucket_starts: list[float]
    trend: list[TrendSeriesResponse]
    # One per heatmap count.
    locations: list[HeatmapLocationResponse]
    heatmap: list[HeatmapRowResponse]
    root_causes: list[RootCauseResponse]
    tone: ToneSummaryResponse


class _ReportQuery:
    """The filters every report endpoint takes."""

    def __init__(
        self,
        # Epoch seconds; from inclusive, to exclusive. Left out: the last
        # 30 days.
        started_from: float | None = Query(None, ge=0),
        started_to: float | None = Query(None, ge=0),
        location_id: str | None = Query(None, max_length=64),
        executive_user_id: str | None = Query(None, max_length=64),
        direction: CallDirection | None = Query(None),
        sentiment: SentimentLabel | None = Query(None),
        category: str | None = Query(None, max_length=100),
        bucket: Literal["auto", "day", "week"] = Query("auto"),
        # The reader's clock ahead of UTC (India: 330), so that days and
        # weeks start at their midnight.
        tz_offset_minutes: int = Query(0, ge=_MIN_TZ_OFFSET, le=_MAX_TZ_OFFSET),
    ) -> None:
        started_to = time.time() if started_to is None else started_to
        if started_from is None:
            started_from = max(0.0, started_to - DEFAULT_RANGE_DAYS * SECONDS_PER_DAY)
        self.filters = ReportFilters(
            started_from=started_from,
            started_to=started_to,
            location_id=location_id,
            executive_user_id=executive_user_id,
            direction=direction,
            sentiment=sentiment,
            category=(category or "").strip() or None,
        )
        self.bucket = None if bucket == "auto" else bucket
        self.tz_offset_minutes = tz_offset_minutes

    def report(self, service: ReportService) -> Report:
        return service.complaint_report(self.filters, self.bucket, self.tz_offset_minutes)


@router.get("/complaints", response_model=ComplaintReportResponse)
async def complaint_report(
    query: _ReportQuery = Depends(),
    service: ReportService = Depends(get_report_service),
    _: User = Depends(_SUPERVISORS),
) -> ComplaintReportResponse:
    report = await run_in_threadpool(query.report, service)
    return ComplaintReportResponse.model_validate(report)


@router.get("/complaints/export")
async def export_complaint_report(
    file_format: Literal["csv", "xlsx", "pdf"] = Query("xlsx", alias="format"),
    query: _ReportQuery = Depends(),
    service: ReportService = Depends(get_report_service),
    _: User = Depends(_SUPERVISORS),
) -> Response:
    content, media_type, filename = await run_in_threadpool(
        lambda: export_report(query.report(service), file_format)
    )
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Management figures (estimates; see app.services.performance) -----------


class FiguresResponse(_Response):
    calls: int
    complaints: int
    probed_complaints: int
    # Rates are 0.0 to 1.0; null when there is nothing to work them out from.
    coverage_score: float | None
    fcr_calls: int
    fcr_resolved: int
    fcr_rate: float | None
    known_customer_complaints: int
    repeat_complaints: int
    repeat_rate: float | None
    churn_low: int
    churn_medium: int
    churn_high: int
    rated_calls: int
    negative_calls: int
    # 1.0 to 5.0.
    csat: float | None
    serious_escalations: int
    questions_accepted: int
    questions_skipped: int
    # Quality audit: calls that raised a complaint, their average score (0
    # to 100), and the category handled worst on average with its score.
    audited_calls: int
    audit_score: float | None
    weakest_category: str | None
    weakest_category_score: float | None


class ExecutiveFiguresResponse(_Response):
    # null: calls with no executive recorded.
    executive_user_id: str | None
    name: str
    figures: FiguresResponse
    # Their calls' tone per day or week (one per bucket_starts entry).
    tone_trend: list[TonePointResponse]


class PerformanceReportResponse(_Response):
    filters: ReportFiltersResponse
    overall: FiguresResponse
    # Most calls first.
    executives: list[ExecutiveFiguresResponse]
    bucket: Literal["day", "week"]
    # When each day or week of the tone trends starts (epoch seconds).
    bucket_starts: list[float]
    tone_trend: list[TonePointResponse]


class AuditPointResponse(_Response):
    # asked_about, used_suggestion, resolved, tone, open_escalation, long_hold.
    rule: str
    points: float
    # The most the rule could have earned; 0 for a call-level adjustment.
    possible: float
    note: str


class CategoryAuditResponse(_Response):
    category: str
    score: float
    points: list[AuditPointResponse]
    # The detector was not sure this complaint was raised at all.
    unsure: bool


class CallAuditResponse(_Response):
    call_id: str
    # 0 to 100; an estimate by fixed rules.
    score: float
    categories: list[CategoryAuditResponse]
    adjustments: list[AuditPointResponse]


@router.get("/performance", response_model=PerformanceReportResponse)
async def performance_report(
    query: _ReportQuery = Depends(),
    service: PerformanceService = Depends(get_performance_service),
    _: User = Depends(_SUPERVISORS),
) -> PerformanceReportResponse:
    report = await run_in_threadpool(
        service.report, query.filters, query.bucket, query.tz_offset_minutes
    )
    return PerformanceReportResponse.model_validate(report)


@router.get("/calls/{call_id}/audit", response_model=CallAuditResponse)
async def call_audit(
    call_id: str,
    service: PerformanceService = Depends(get_performance_service),
    _: User = Depends(_SUPERVISORS),
) -> CallAuditResponse:
    """How the call was handled, scored by fixed rules (an estimate), with
    a score per complaint category and the reason for each point."""
    audit = await run_in_threadpool(service.audit, call_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="There is no such call.")
    return CallAuditResponse.model_validate(audit)


@router.get("/performance/export")
async def export_performance_report(
    file_format: Literal["csv", "xlsx"] = Query("xlsx", alias="format"),
    query: _ReportQuery = Depends(),
    service: PerformanceService = Depends(get_performance_service),
    _: User = Depends(_SUPERVISORS),
) -> Response:
    content, media_type, filename = await run_in_threadpool(
        lambda: export_scorecard(
            service.report(query.filters, query.bucket, query.tz_offset_minutes),
            file_format,
            query.tz_offset_minutes,
        )
    )
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
