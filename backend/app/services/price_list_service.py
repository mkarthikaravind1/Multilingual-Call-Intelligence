"""The service centre's price list: what the estimator prices calls with,
and what supervisors upload, edit, export and restore."""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.estimation.default_pricing import DEFAULT_PRICE_LIST_ROWS, DEFAULT_PRICE_LIST_SETTINGS
from app.estimation.price_list import (
    PriceListBuild,
    PriceListIssue,
    PriceListRow,
    PriceListSettings,
    build_pricing_config,
)
from app.estimation.price_list_io import export_csv, export_xlsx, parse_price_list
from app.estimation.pricing_config import PricingConfig
from app.services.price_list_repository import PriceListRepository, PriceListVersionInfo

logger = logging.getLogger(__name__)


class InvalidPriceListError(ValueError):
    def __init__(self, errors: tuple[PriceListIssue, ...]) -> None:
        super().__init__("; ".join(e.message for e in errors[:5]))
        self.errors = errors


class PriceListVersionNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class CurrentPriceList:
    settings: PriceListSettings
    rows: tuple[PriceListRow, ...]
    # None: the built-in sample price list (nothing saved yet).
    version: PriceListVersionInfo | None
    build: PriceListBuild


@dataclass(frozen=True)
class PriceListPreview:
    rows: tuple[PriceListRow, ...]
    # The spreadsheet row each row came from.
    sheet_rows: tuple[int, ...]
    errors: tuple[PriceListIssue, ...]
    warnings: tuple[PriceListIssue, ...]
    service_count: int
    vehicle_model_count: int


class PriceListService:
    def __init__(
        self,
        repository: PriceListRepository,
        *,
        cache_seconds: float = 30.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._repository = repository
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: PricingConfig | None = None
        self._cached_at = 0.0

    # --- What the estimator reads ---

    def pricing(self) -> PricingConfig:
        """The price list in use. Kept for cache_seconds, so other API
        instances pick up a save within that time; a save on this instance
        is used at once. If the database cannot be read, the last known
        price list is kept."""
        now = self._clock()
        cached = self._cached
        if cached is not None and now - self._cached_at < self._cache_seconds:
            return cached
        try:
            config = self.current().build.config
        except Exception:
            if cached is None:
                raise
            logger.warning("Could not reload the price list; using the last one read.", exc_info=True)
            # Try the database again only after cache_seconds, so callers do
            # not each wait on it while it is down.
            with self._lock:
                self._cached_at = now
            return cached
        with self._lock:
            self._cached, self._cached_at = config, now
        return config

    # --- What supervisors see and change ---

    def current(self) -> CurrentPriceList:
        version = self._repository.get_active()
        if version is None:
            settings, rows, info = DEFAULT_PRICE_LIST_SETTINGS, DEFAULT_PRICE_LIST_ROWS, None
        else:
            settings, rows, info = version.settings, version.rows, version.info
        build = build_pricing_config(settings, rows)
        if build.config is None:
            # Saved lists were valid when saved; only a rule change could
            # make one invalid. Price with the sample list rather than fail.
            logger.error(
                "The saved price list %s is no longer valid (%s); using the sample price list.",
                None if info is None else info.version_id,
                "; ".join(e.message for e in build.errors[:3]),
            )
            build = build_pricing_config(DEFAULT_PRICE_LIST_SETTINGS, DEFAULT_PRICE_LIST_ROWS)
        return CurrentPriceList(settings, rows, info, build)

    def preview_upload(self, filename: str, content: bytes) -> PriceListPreview:
        """Read an uploaded sheet and check it, without saving anything.
        Raises PriceListFileError when the file cannot be read at all."""
        parsed = parse_price_list(filename, content)
        settings = self.current().settings
        build = build_pricing_config(settings, parsed.rows)

        def at_sheet_row(issue: PriceListIssue) -> PriceListIssue:
            # Point the problem at the spreadsheet row it is on.
            if issue.row is None:
                return issue
            return PriceListIssue(issue.severity, issue.message, parsed.sheet_rows[issue.row - 1])

        return PriceListPreview(
            rows=parsed.rows,
            sheet_rows=parsed.sheet_rows,
            errors=parsed.errors + tuple(at_sheet_row(issue) for issue in build.errors),
            warnings=tuple(at_sheet_row(issue) for issue in build.warnings),
            service_count=build.service_count,
            vehicle_model_count=build.vehicle_model_count,
        )

    def save(
        self,
        settings: PriceListSettings,
        rows: tuple[PriceListRow, ...],
        *,
        user: str,
        source: str = "edit",
        note: str | None = None,
    ) -> CurrentPriceList:
        build = build_pricing_config(settings, rows)
        if build.config is None:
            raise InvalidPriceListError(build.errors)
        settings = PriceListSettings(
            currency=settings.currency.strip().upper(),
            labour_hourly_rate=settings.labour_hourly_rate,
            labour_gst_percent=settings.labour_gst_percent,
            default_gst_percent=settings.default_gst_percent,
        )
        version = self._repository.add(
            settings,
            tuple(rows),
            created_at=self._clock(),
            created_by=user,
            source=source,
            note=note,
        )
        logger.info(
            "%s saved price list version %s (%s, %d rows)",
            user, version.info.version_id, source, len(rows),
        )
        self._use(build.config)
        return CurrentPriceList(version.settings, version.rows, version.info, build)

    def restore(self, version_id: int, *, user: str) -> CurrentPriceList:
        old = self._repository.get(version_id)
        if old is None:
            raise PriceListVersionNotFoundError(version_id)
        return self.save(
            old.settings,
            old.rows,
            user=user,
            source="restore",
            note=f"Restored version {version_id}",
        )

    def versions(self) -> tuple[PriceListVersionInfo, ...]:
        return self._repository.list_versions()

    def export(self, file_format: str) -> tuple[bytes, str, str]:
        """(content, media type, filename) of the price list in use."""
        rows = self.current().rows
        if file_format == "csv":
            return export_csv(rows), "text/csv; charset=utf-8", "price-list.csv"
        return (
            export_xlsx(rows),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "price-list.xlsx",
        )

    def _use(self, config: PricingConfig) -> None:
        with self._lock:
            self._cached, self._cached_at = config, self._clock()
