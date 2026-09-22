from dataclasses import dataclass
from decimal import Decimal

from app.domain.service_estimate import EstimatedPart


@dataclass(frozen=True)
class ServiceRule:
    service_name: str
    keywords: tuple[str, ...]
    parts: tuple[EstimatedPart, ...]
    labour_hours: float
    duration_hours: float

    def __post_init__(self) -> None:
        if not self.service_name.strip():
            raise ValueError("service_name must not be empty.")
        if not self.keywords or any(not keyword.strip() for keyword in self.keywords):
            raise ValueError("keywords must contain only non-empty keywords.")


@dataclass(frozen=True)
class PricingConfig:
    currency: str
    labour_hourly_rate: Decimal
    rules: tuple[ServiceRule, ...]

    def __post_init__(self) -> None:
        if not self.currency.strip():
            raise ValueError("currency must not be empty.")