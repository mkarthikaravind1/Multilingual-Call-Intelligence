from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from app.domain.service_estimate import EstimatedPart, LabourEstimate, ServiceEstimate


def make_estimate(**overrides) -> ServiceEstimate:
    values = {
        "service_name": "Oil Change",
        "currency": "INR",
        "parts": (
            EstimatedPart("Engine oil", 4, Decimal("500")),
            EstimatedPart("Oil filter", 1, Decimal("300")),
        ),
        "labour": LabourEstimate(hours=0.5, hourly_rate=Decimal("600")),
        "estimated_duration_hours": 1.0,
    }
    values.update(overrides)
    return ServiceEstimate(**values)


def test_part_total_price_uses_quantity() -> None:
    assert EstimatedPart("Filter", 3, Decimal("100")).total_price == Decimal("300")


def test_labour_total_cost_uses_hours_and_rate() -> None:
    assert LabourEstimate(hours=1.5, hourly_rate=Decimal("600")).total_cost == Decimal("900")


def test_estimate_cost_is_parts_plus_labour() -> None:
    estimate = make_estimate()
    assert estimate.parts_cost == Decimal("2300")
    assert estimate.labour_cost == Decimal("300")
    assert estimate.estimated_cost == Decimal("2600")


def test_estimate_without_parts_costs_labour_only() -> None:
    estimate = make_estimate(parts=())
    assert estimate.parts_cost == Decimal("0")
    assert estimate.estimated_cost == Decimal("300")


def test_estimate_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        make_estimate().service_name = "Other" # type: ignore


@pytest.mark.parametrize("name", ["", "   "])
def test_part_rejects_blank_name(name: str) -> None:
    with pytest.raises(ValueError):
        EstimatedPart(name, 1, Decimal("10"))


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True])
def test_part_rejects_invalid_quantity(quantity) -> None:
    with pytest.raises(ValueError):
        EstimatedPart("Filter", quantity, Decimal("10"))


@pytest.mark.parametrize(
    "price", [Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), 10.0, "10"]
)
def test_part_rejects_invalid_unit_price(price) -> None:
    with pytest.raises(ValueError):
        EstimatedPart("Filter", 1, price)


@pytest.mark.parametrize("hours", [0, -1, float("nan"), float("inf"), True, "1"])
def test_labour_rejects_invalid_hours(hours) -> None:
    with pytest.raises(ValueError):
        LabourEstimate(hours=hours, hourly_rate=Decimal("600"))


def test_labour_rejects_invalid_rate() -> None:
    with pytest.raises(ValueError):
        LabourEstimate(hours=1.0, hourly_rate=Decimal("-5"))


@pytest.mark.parametrize("hours", [0, -2.0, float("nan")])
def test_estimate_rejects_invalid_duration(hours: float) -> None:
    with pytest.raises(ValueError):
        make_estimate(estimated_duration_hours=hours)


@pytest.mark.parametrize("field", ["service_name", "currency"])
def test_estimate_rejects_blank_text_fields(field: str) -> None:
    with pytest.raises(ValueError):
        make_estimate(**{field: "  "})


def test_estimate_requires_parts_tuple() -> None:
    with pytest.raises(ValueError):
        make_estimate(parts=[EstimatedPart("Filter", 1, Decimal("10"))])


def test_estimate_rejects_non_part_items() -> None:
    with pytest.raises(ValueError):
        make_estimate(parts=("filter",))


def test_estimate_requires_labour_estimate() -> None:
    with pytest.raises(ValueError):
        make_estimate(labour=None)