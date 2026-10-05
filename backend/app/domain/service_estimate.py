import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


def _require_amount(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError(f"{field_name} must be a non-negative Decimal.")


def _require_hours(value: float, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{field_name} must be a positive number of hours.")


@dataclass(frozen=True)
class EstimatedPart:
    name: str
    quantity: int
    unit_price: Decimal

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Part name must not be empty.")
        if (
            isinstance(self.quantity, bool)
            or not isinstance(self.quantity, int)
            or self.quantity < 1
        ):
            raise ValueError("Part quantity must be a positive integer.")
        _require_amount(self.unit_price, "unit_price")

    @property
    def total_price(self) -> Decimal:
        return self.unit_price * self.quantity


@dataclass(frozen=True)
class LabourEstimate:
    hours: float
    hourly_rate: Decimal

    def __post_init__(self) -> None:
        _require_hours(self.hours, "Labour hours")
        _require_amount(self.hourly_rate, "hourly_rate")

    @property
    def total_cost(self) -> Decimal:
        return self.hourly_rate * Decimal(str(self.hours))


@dataclass(frozen=True)
class ServiceEstimate:
    service_name: str
    currency: str
    parts: tuple[EstimatedPart, ...]
    labour: LabourEstimate
    estimated_duration_hours: float

    def __post_init__(self) -> None:
        if not self.service_name.strip():
            raise ValueError("service_name must not be empty.")
        if not self.currency.strip():
            raise ValueError("currency must not be empty.")
        if not isinstance(self.parts, tuple) or not all(
            isinstance(part, EstimatedPart) for part in self.parts
        ):
            raise ValueError("parts must be a tuple of EstimatedPart.")
        if not isinstance(self.labour, LabourEstimate):
            raise ValueError("labour must be a LabourEstimate.")
        _require_hours(self.estimated_duration_hours, "estimated_duration_hours")

    @property
    def parts_cost(self) -> Decimal:
        return sum((part.total_price for part in self.parts), Decimal("0"))

    @property
    def labour_cost(self) -> Decimal:
        return self.labour.total_cost

    @property
    def estimated_cost(self) -> Decimal:
        return self.parts_cost + self.labour_cost

@dataclass(frozen=True)
class CallServiceEstimate:
    """Every service that came up in a call, each priced from the price
    list, and what they come to together."""

    currency: str
    services: tuple[ServiceEstimate, ...]

    def __post_init__(self) -> None:
        if not self.currency.strip():
            raise ValueError("currency must not be empty.")
        if (
            not isinstance(self.services, tuple)
            or not self.services
            or not all(isinstance(s, ServiceEstimate) for s in self.services)
        ):
            raise ValueError("services must be a non-empty tuple of ServiceEstimate.")
        if any(s.currency != self.currency for s in self.services):
            raise ValueError("Every service must be priced in the estimate's currency.")

    @property
    def service_names(self) -> tuple[str, ...]:
        return tuple(s.service_name for s in self.services)

    @property
    def parts_cost(self) -> Decimal:
        return sum((s.parts_cost for s in self.services), Decimal("0"))

    @property
    def labour_cost(self) -> Decimal:
        return sum((s.labour_cost for s in self.services), Decimal("0"))

    @property
    def estimated_cost(self) -> Decimal:
        return self.parts_cost + self.labour_cost

    @property
    def estimated_duration_hours(self) -> float:
        # Services are done one after another: the visit takes their sum.
        return sum(s.estimated_duration_hours for s in self.services)


# JSON form, shared by the live-analysis store and the database. Only the
# inputs are kept (totals are properties); amounts are strings so no
# precision is lost.
def call_estimate_to_json(estimate: CallServiceEstimate) -> dict[str, Any]:
    return {
        "currency": estimate.currency,
        "services": [_service_to_json(s) for s in estimate.services],
    }


def call_estimate_from_json(data: Mapping[str, Any]) -> CallServiceEstimate:
    if "services" not in data:
        # Stored before estimates covered the whole call: one service.
        service = _service_from_json(data)
        return CallServiceEstimate(currency=service.currency, services=(service,))
    return CallServiceEstimate(
        currency=data["currency"],
        services=tuple(_service_from_json(s) for s in data["services"]),
    )


def _service_to_json(estimate: ServiceEstimate) -> dict[str, Any]:
    return {
        "service_name": estimate.service_name,
        "currency": estimate.currency,
        "parts": [
            {"name": part.name, "quantity": part.quantity, "unit_price": str(part.unit_price)}
            for part in estimate.parts
        ],
        "labour": {
            "hours": estimate.labour.hours,
            "hourly_rate": str(estimate.labour.hourly_rate),
        },
        "estimated_duration_hours": estimate.estimated_duration_hours,
    }


def _service_from_json(data: Mapping[str, Any]) -> ServiceEstimate:
    return ServiceEstimate(
        service_name=data["service_name"],
        currency=data["currency"],
        parts=tuple(
            EstimatedPart(
                name=part["name"],
                quantity=part["quantity"],
                unit_price=Decimal(part["unit_price"]),
            )
            for part in data["parts"]
        ),
        labour=LabourEstimate(
            hours=data["labour"]["hours"],
            hourly_rate=Decimal(data["labour"]["hourly_rate"]),
        ),
        estimated_duration_hours=data["estimated_duration_hours"],
    )
