"""The sample price list a new deployment starts with, until the supervisor
uploads the service centre's own (Price List page). Prices are before GST."""

from decimal import Decimal

from app.estimation.price_list import PriceListRow, PriceListSettings, build_pricing_config

DEFAULT_PRICE_LIST_SETTINGS = PriceListSettings(
    currency="INR",
    labour_hourly_rate=Decimal("600"),
    labour_gst_percent=Decimal("18"),
    default_gst_percent=Decimal("18"),
)

DEFAULT_PRICE_LIST_ROWS: tuple[PriceListRow, ...] = (
    PriceListRow(
        service="General Service",
        part="Engine oil (1 L)",
        quantity=4,
        unit_price=Decimal("550"),
        labour_hours=3.0,
        duration_hours=6.0,
        keywords=("general service", "periodic service", "full service"),
        includes=("Oil Change",),
    ),
    PriceListRow(service="General Service", part="Oil filter", quantity=1, unit_price=Decimal("350")),
    PriceListRow(service="General Service", part="Air filter", quantity=1, unit_price=Decimal("450")),
    PriceListRow(
        service="Oil Change",
        part="Engine oil (1 L)",
        quantity=4,
        unit_price=Decimal("550"),
        labour_hours=0.5,
        duration_hours=1.0,
        keywords=("oil change", "engine oil", "oil service"),
    ),
    PriceListRow(service="Oil Change", part="Oil filter", quantity=1, unit_price=Decimal("350")),
    PriceListRow(
        service="Brake Pad Replacement",
        part="Brake pad set",
        quantity=1,
        unit_price=Decimal("2800"),
        labour_hours=1.5,
        duration_hours=3.0,
        keywords=("brake",),
    ),
    PriceListRow(
        service="Battery Replacement",
        part="Battery",
        quantity=1,
        unit_price=Decimal("5500"),
        labour_hours=0.5,
        duration_hours=1.0,
        keywords=("battery",),
    ),
)

_build = build_pricing_config(DEFAULT_PRICE_LIST_SETTINGS, DEFAULT_PRICE_LIST_ROWS)
assert _build.config is not None, _build.errors
DEFAULT_PRICING_CONFIG = _build.config
