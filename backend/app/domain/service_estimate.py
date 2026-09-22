import math
from dataclasses import dataclass
from decimal import Decimal


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