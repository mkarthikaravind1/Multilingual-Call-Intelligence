from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.estimation.price_list import (
    MAX_ROWS,
    PriceListIssue,
    PriceListRow,
    PriceListSettings,
)
from app.services.price_list_repository import PriceListVersionInfo
from app.services.price_list_service import CurrentPriceList, PriceListPreview


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PriceListSettingsBody(BaseModel):
    currency: str = Field(min_length=1, max_length=8)
    labour_hourly_rate: Decimal = Field(ge=0)
    labour_gst_percent: Decimal = Field(ge=0, le=100)
    default_gst_percent: Decimal = Field(ge=0, le=100)

    def to_domain(self) -> PriceListSettings:
        return PriceListSettings(
            currency=self.currency,
            labour_hourly_rate=self.labour_hourly_rate,
            labour_gst_percent=self.labour_gst_percent,
            default_gst_percent=self.default_gst_percent,
        )

    @classmethod
    def from_domain(cls, settings: PriceListSettings) -> "PriceListSettingsBody":
        return cls(
            currency=settings.currency,
            labour_hourly_rate=settings.labour_hourly_rate,
            labour_gst_percent=settings.labour_gst_percent,
            default_gst_percent=settings.default_gst_percent,
        )


class PriceListRowBody(BaseModel):
    # Values are checked when the list is built, so every problem is
    # reported with the row it is on rather than as a request error.
    service: str = Field(max_length=200)
    vehicle_model: str | None = Field(default=None, max_length=200)
    part: str | None = Field(default=None, max_length=200)
    quantity: int | None = None
    unit_price: Decimal | None = None
    gst_percent: Decimal | None = None
    labour_hours: float | None = None
    duration_hours: float | None = None
    keywords: list[str] = Field(default_factory=list, max_length=50)
    includes: list[str] = Field(default_factory=list, max_length=50)

    def to_domain(self) -> PriceListRow:
        return PriceListRow(
            service=self.service,
            vehicle_model=_blank_to_none(self.vehicle_model),
            part=_blank_to_none(self.part),
            quantity=self.quantity,
            unit_price=self.unit_price,
            gst_percent=self.gst_percent,
            labour_hours=self.labour_hours,
            duration_hours=self.duration_hours,
            keywords=tuple(k.strip() for k in self.keywords if k.strip()),
            includes=tuple(i.strip() for i in self.includes if i.strip()),
        )

    @classmethod
    def from_domain(cls, row: PriceListRow) -> "PriceListRowBody":
        return cls(
            service=row.service,
            vehicle_model=row.vehicle_model,
            part=row.part,
            quantity=row.quantity,
            unit_price=row.unit_price,
            gst_percent=row.gst_percent,
            labour_hours=row.labour_hours,
            duration_hours=row.duration_hours,
            keywords=list(row.keywords),
            includes=list(row.includes),
        )


def _blank_to_none(value: str | None) -> str | None:
    return value.strip() if value is not None and value.strip() else None


class SavePriceListRequest(_Request):
    settings: PriceListSettingsBody
    rows: list[PriceListRowBody] = Field(max_length=MAX_ROWS)
    # "upload" when the rows come from an uploaded sheet.
    source: Literal["edit", "upload"] = "edit"
    # e.g. the uploaded file's name.
    note: str | None = Field(default=None, max_length=200)


class PriceListIssueResponse(_Response):
    severity: Literal["error", "warning"]
    message: str
    row: int | None


class PriceListVersionResponse(_Response):
    version_id: int
    created_at: float
    created_by: str | None
    source: str
    note: str | None
    row_count: int
    is_active: bool


class PriceListResponse(BaseModel):
    settings: PriceListSettingsBody
    rows: list[PriceListRowBody]
    # None while the built-in sample price list is in use.
    version: PriceListVersionResponse | None
    service_count: int
    vehicle_model_count: int
    warnings: list[PriceListIssueResponse]

    @classmethod
    def from_current(cls, current: CurrentPriceList) -> "PriceListResponse":
        return cls(
            settings=PriceListSettingsBody.from_domain(current.settings),
            rows=[PriceListRowBody.from_domain(row) for row in current.rows],
            version=_version(current.version),
            service_count=current.build.service_count,
            vehicle_model_count=current.build.vehicle_model_count,
            warnings=[_issue(issue) for issue in current.build.warnings],
        )


class PriceListPreviewResponse(BaseModel):
    rows: list[PriceListRowBody]
    # The spreadsheet row each row came from; issues use these numbers.
    sheet_rows: list[int]
    errors: list[PriceListIssueResponse]
    warnings: list[PriceListIssueResponse]
    service_count: int
    vehicle_model_count: int

    @classmethod
    def from_preview(cls, preview: PriceListPreview) -> "PriceListPreviewResponse":
        return cls(
            rows=[PriceListRowBody.from_domain(row) for row in preview.rows],
            sheet_rows=list(preview.sheet_rows),
            errors=[_issue(issue) for issue in preview.errors],
            warnings=[_issue(issue) for issue in preview.warnings],
            service_count=preview.service_count,
            vehicle_model_count=preview.vehicle_model_count,
        )


def _issue(issue: PriceListIssue) -> PriceListIssueResponse:
    return PriceListIssueResponse.model_validate(issue)


def _version(info: PriceListVersionInfo | None) -> PriceListVersionResponse | None:
    return None if info is None else PriceListVersionResponse.model_validate(info)
