import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from app.domain.service_estimate import EstimatedPart

_NON_ALPHANUMERIC = re.compile(r"[^0-9a-z]+")


def normalize_model(model: str) -> str:
    """"Swift-Dzire", "swift  dzire" and "SWIFT DZIRE" are the same model."""
    return _NON_ALPHANUMERIC.sub(" ", model.casefold()).strip()


@dataclass(frozen=True)
class ServiceRule:
    service_name: str
    keywords: tuple[str, ...]
    parts: tuple[EstimatedPart, ...]
    labour_hours: float
    duration_hours: float
    # Other services this one already includes (General Service includes
    # the oil change): when both come up, only this one is charged.
    covers: tuple[str, ...] = ()
    # The vehicle model these prices are for; None: every model.
    vehicle_model: str | None = None

    def __post_init__(self) -> None:
        if not self.service_name.strip():
            raise ValueError("service_name must not be empty.")
        if not self.keywords or any(not keyword.strip() for keyword in self.keywords):
            raise ValueError("keywords must contain only non-empty keywords.")
        if self.vehicle_model is not None and not normalize_model(self.vehicle_model):
            raise ValueError("vehicle_model must not be blank when provided.")


@dataclass(frozen=True)
class PricedRule:
    rule: ServiceRule
    # The service has model-specific prices, but none for this vehicle (or
    # the vehicle is unknown): this is the all-models price.
    approximate: bool


@dataclass(frozen=True)
class PricingConfig:
    currency: str
    labour_hourly_rate: Decimal
    rules: tuple[ServiceRule, ...]
    labour_gst_percent: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.currency.strip():
            raise ValueError("currency must not be empty.")

    @property
    def service_names(self) -> tuple[str, ...]:
        """Each service once, in price-list order (a service priced for
        several models has several rules)."""
        names: dict[str, str] = {}
        for rule in self.rules:
            names.setdefault(rule.service_name.casefold(), rule.service_name)
        return tuple(names.values())

    @property
    def vehicle_models(self) -> tuple[str, ...]:
        models: dict[str, str] = {}
        for rule in self.rules:
            if rule.vehicle_model is not None:
                models.setdefault(normalize_model(rule.vehicle_model), rule.vehicle_model)
        return tuple(models.values())

    def keywords_for(self, service_name: str) -> tuple[str, ...]:
        wanted = service_name.strip().casefold()
        keywords: dict[str, str] = {}
        for rule in self.rules:
            if rule.service_name.casefold() == wanted:
                for keyword in rule.keywords:
                    keywords.setdefault(keyword.casefold(), keyword)
        return tuple(keywords.values())

    def rule_for(self, service_name: str) -> ServiceRule | None:
        """The service's all-models rule, else its first rule."""
        wanted = service_name.strip().casefold()
        matching = [r for r in self.rules if r.service_name.casefold() == wanted]
        return next((r for r in matching if r.vehicle_model is None), None) or next(
            iter(matching), None
        )

    def match_vehicle_model(self, vehicle_model: str | None) -> str | None:
        """The price-list model a vehicle is: the same name, else the
        longest price-list model named in it ("Maruti Swift VXi" is a
        "Swift"). None when the price list does not price it."""
        if not vehicle_model:
            return None
        wanted = normalize_model(vehicle_model)
        if not wanted:
            return None
        padded = f" {wanted} "
        best: str | None = None
        for model in self.vehicle_models:
            normalized = normalize_model(model)
            if normalized == wanted:
                return model
            if f" {normalized} " in padded and (
                best is None or len(normalized) > len(normalize_model(best))
            ):
                best = model
        return best

    def price_for(self, service_name: str, vehicle_model: str | None = None) -> PricedRule | None:
        """The rule that prices this service for this vehicle: its own
        model's rule, else the all-models rule. None when there is neither."""
        wanted = service_name.strip().casefold()
        matching = [r for r in self.rules if r.service_name.casefold() == wanted]
        if not matching:
            return None
        model = self.match_vehicle_model(vehicle_model)
        if model is not None:
            key = normalize_model(model)
            for rule in matching:
                if rule.vehicle_model is not None and normalize_model(rule.vehicle_model) == key:
                    return PricedRule(rule, approximate=False)
        generic = next((r for r in matching if r.vehicle_model is None), None)
        if generic is None:
            return None
        has_model_prices = any(r.vehicle_model is not None for r in matching)
        return PricedRule(generic, approximate=has_model_prices)


# A fixed price list, or a function returning the one in use (it can change
# while the application runs: see PriceListService.pricing).
PricingSource = PricingConfig | Callable[[], PricingConfig]


def pricing_source(pricing: PricingSource) -> Callable[[], PricingConfig]:
    if isinstance(pricing, PricingConfig):
        return lambda: pricing
    return pricing
