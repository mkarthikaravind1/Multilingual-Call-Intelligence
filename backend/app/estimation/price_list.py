"""The service centre's price list as the supervisor keeps it: one row per
vehicle model, service and part, plus a few settings (labour rate, GST).

Rows are what is uploaded, edited and stored; build_pricing_config turns
them into the PricingConfig the estimator reads, reporting every problem
with the row it is on. Prices are before GST.
"""

import math
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from app.domain.service_estimate import EstimatedPart
from app.estimation.pricing_config import PricingConfig, ServiceRule, normalize_model

MAX_ROWS = 5000
_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class PriceListSettings:
    currency: str
    labour_hourly_rate: Decimal
    # GST on labour, and on a part whose row leaves GST % blank.
    labour_gst_percent: Decimal
    default_gst_percent: Decimal


@dataclass(frozen=True)
class PriceListRow:
    service: str
    # Blank: the price for every model without a row of its own.
    vehicle_model: str | None = None
    # Blank: a row that only sets the service's labour/duration/keywords.
    part: str | None = None
    quantity: int | None = None
    unit_price: Decimal | None = None
    # Blank: the default GST %.
    gst_percent: Decimal | None = None
    labour_hours: float | None = None
    duration_hours: float | None = None
    # Words that mean this service in a call (English); the service name
    # itself always counts.
    keywords: tuple[str, ...] = ()
    # Other services this one already includes (charged once).
    includes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PriceListIssue:
    severity: Literal["error", "warning"]
    message: str
    # 1-based position in the row list; None for the list as a whole.
    row: int | None = None


@dataclass(frozen=True)
class PriceListBuild:
    config: PricingConfig | None
    errors: tuple[PriceListIssue, ...] = ()
    warnings: tuple[PriceListIssue, ...] = ()
    service_count: int = 0
    vehicle_model_count: int = 0


@dataclass
class _Group:
    service: str
    vehicle_model: str | None
    rows: list[int] = field(default_factory=list)
    parts: list[EstimatedPart] = field(default_factory=list)
    labour_hours: set[float] = field(default_factory=set)
    duration_hours: set[float] = field(default_factory=set)


def build_pricing_config(
    settings: PriceListSettings, rows: tuple[PriceListRow, ...] | list[PriceListRow]
) -> PriceListBuild:
    errors: list[PriceListIssue] = []
    warnings: list[PriceListIssue] = []

    def error(message: str, row: int | None = None) -> None:
        errors.append(PriceListIssue("error", message, row))

    def warning(message: str, row: int | None = None) -> None:
        warnings.append(PriceListIssue("warning", message, row))

    _check_settings(settings, error)
    if not rows:
        error("The price list has no rows.")
    if len(rows) > MAX_ROWS:
        error(f"The price list has {len(rows)} rows; at most {MAX_ROWS} are allowed.")
    if errors:
        return PriceListBuild(None, tuple(errors), tuple(warnings))

    groups: dict[tuple[str, str], _Group] = {}
    service_names: dict[str, str] = {}
    keywords: dict[str, dict[str, str]] = {}
    includes: dict[str, list[tuple[str, int]]] = {}

    for number, row in enumerate(rows, start=1):
        service = (row.service or "").strip()
        if not service:
            error("Service is missing.", number)
            continue
        key = service.casefold()
        service_names.setdefault(key, service)
        model = (row.vehicle_model or "").strip() or None
        if model is not None and not normalize_model(model):
            error(f"Vehicle model {model!r} has no letters or digits.", number)
            continue
        group = groups.setdefault(
            (normalize_model(model) if model else "", key), _Group(service, model)
        )
        group.rows.append(number)

        for keyword in row.keywords:
            if keyword.strip():
                keywords.setdefault(key, {}).setdefault(keyword.strip().casefold(), keyword.strip())
        for included in row.includes:
            if included.strip():
                includes.setdefault(key, []).append((included.strip(), number))

        if row.labour_hours is not None:
            if _valid_hours(row.labour_hours):
                group.labour_hours.add(float(row.labour_hours))
            else:
                error("Labour hours must be a number above 0.", number)
        if row.duration_hours is not None:
            if _valid_hours(row.duration_hours):
                group.duration_hours.add(float(row.duration_hours))
            else:
                error("Duration hours must be a number above 0.", number)

        part = _part_from_row(row, settings, number, error)
        if part is not None:
            group.parts.append(part)

    rules: list[ServiceRule] = []
    for group in groups.values():
        where = _describe(group)
        first_row = group.rows[0]
        if len(group.labour_hours) > 1:
            error(f"{where}: rows give different labour hours.", first_row)
            continue
        if len(group.duration_hours) > 1:
            error(f"{where}: rows give different duration hours.", first_row)
            continue
        if not group.labour_hours:
            error(f"{where}: labour hours are missing (fill them in on one of its rows).", first_row)
            continue
        labour_hours = next(iter(group.labour_hours))
        duration_hours = next(iter(group.duration_hours), labour_hours)

        key = group.service.casefold()
        covered: list[str] = []
        for included, number in includes.get(key, []):
            target = service_names.get(included.casefold())
            if target is None:
                warning(f"{where}: includes {included!r}, which is not in the price list.", number)
            elif target.casefold() == key:
                warning(f"{where}: a service cannot include itself.", number)
            elif target not in covered:
                covered.append(target)
        rules.append(
            ServiceRule(
                service_name=service_names[key],
                keywords=tuple(
                    ({key: service_names[key]} | keywords.get(key, {})).values()
                ),
                parts=tuple(group.parts),
                labour_hours=labour_hours,
                duration_hours=duration_hours,
                covers=tuple(covered),
                vehicle_model=group.vehicle_model,
            )
        )

    for key, name in service_names.items():
        service_rules = [g for g in groups.values() if g.service.casefold() == key]
        if service_rules and all(g.vehicle_model is not None for g in service_rules):
            warning(
                f"{name!r} has prices only for specific models: calls about any other "
                "model, or an unknown one, get no estimate for it. Add a row with a "
                "blank vehicle model to give it an all-models price.",
                service_rules[0].rows[0],
            )

    if errors:
        return PriceListBuild(None, tuple(errors), tuple(_dedupe(warnings)))
    config = PricingConfig(
        currency=settings.currency.strip().upper(),
        labour_hourly_rate=settings.labour_hourly_rate,
        rules=tuple(rules),
        labour_gst_percent=settings.labour_gst_percent,
    )
    return PriceListBuild(
        config,
        (),
        tuple(_dedupe(warnings)),
        service_count=len(service_names),
        vehicle_model_count=len(config.vehicle_models),
    )


def _check_settings(settings: PriceListSettings, error) -> None:
    if not settings.currency or not settings.currency.strip():
        error("Currency is missing.")
    if not _valid_amount(settings.labour_hourly_rate):
        error("The labour hourly rate must be a number of 0 or more.")
    if not _valid_percent(settings.labour_gst_percent):
        error("Labour GST % must be between 0 and 100.")
    if not _valid_percent(settings.default_gst_percent):
        error("The default GST % must be between 0 and 100.")


def _part_from_row(
    row: PriceListRow, settings: PriceListSettings, number: int, error
) -> EstimatedPart | None:
    part = (row.part or "").strip()
    if not part:
        if row.unit_price is not None or row.quantity is not None:
            error("Unit price or quantity given without a part name.", number)
        return None
    if row.unit_price is None:
        error(f"Part {part!r} has no unit price.", number)
        return None
    if not _valid_amount(row.unit_price):
        error(f"Part {part!r}: the unit price must be a number of 0 or more.", number)
        return None
    quantity = 1 if row.quantity is None else row.quantity
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        error(f"Part {part!r}: the quantity must be a whole number of 1 or more.", number)
        return None
    gst = settings.default_gst_percent if row.gst_percent is None else row.gst_percent
    if not _valid_percent(gst):
        error(f"Part {part!r}: GST % must be between 0 and 100.", number)
        return None
    return EstimatedPart(part, quantity, row.unit_price, gst)


def _describe(group: _Group) -> str:
    model = group.vehicle_model or "all models"
    return f"{group.service!r} ({model})"


def _valid_amount(value: Any) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value >= 0


def _valid_percent(value: Any) -> bool:
    return _valid_amount(value) and value <= _HUNDRED


def _valid_hours(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value > 0
    )


def _dedupe(issues: list[PriceListIssue]) -> list[PriceListIssue]:
    seen: set[tuple] = set()
    unique = []
    for issue in issues:
        key = (issue.severity, issue.message, issue.row)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


# --- JSON form (storage) -------------------------------------------------
# Amounts are strings so no precision is lost; blank cells are None.


def settings_to_json(settings: PriceListSettings) -> dict[str, Any]:
    return {
        "currency": settings.currency,
        "labour_hourly_rate": str(settings.labour_hourly_rate),
        "labour_gst_percent": str(settings.labour_gst_percent),
        "default_gst_percent": str(settings.default_gst_percent),
    }


def settings_from_json(data: dict[str, Any]) -> PriceListSettings:
    return PriceListSettings(
        currency=data["currency"],
        labour_hourly_rate=Decimal(data["labour_hourly_rate"]),
        labour_gst_percent=Decimal(data["labour_gst_percent"]),
        default_gst_percent=Decimal(data["default_gst_percent"]),
    )


def row_to_json(row: PriceListRow) -> dict[str, Any]:
    return {
        "service": row.service,
        "vehicle_model": row.vehicle_model,
        "part": row.part,
        "quantity": row.quantity,
        "unit_price": None if row.unit_price is None else str(row.unit_price),
        "gst_percent": None if row.gst_percent is None else str(row.gst_percent),
        "labour_hours": row.labour_hours,
        "duration_hours": row.duration_hours,
        "keywords": list(row.keywords),
        "includes": list(row.includes),
    }


def row_from_json(data: dict[str, Any]) -> PriceListRow:
    return PriceListRow(
        service=data["service"],
        vehicle_model=data.get("vehicle_model"),
        part=data.get("part"),
        quantity=data.get("quantity"),
        unit_price=_decimal_or_none(data.get("unit_price")),
        gst_percent=_decimal_or_none(data.get("gst_percent")),
        labour_hours=data.get("labour_hours"),
        duration_hours=data.get("duration_hours"),
        keywords=tuple(data.get("keywords") or ()),
        includes=tuple(data.get("includes") or ()),
    )


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None
