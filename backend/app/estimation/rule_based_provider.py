from app.domain.service_estimate import LabourEstimate, ServiceEstimate
from app.estimation.pricing_config import PricingConfig, ServiceRule
from app.estimation.provider import ServiceEstimationProvider


class RuleBasedEstimationProvider(ServiceEstimationProvider):
    def __init__(self, pricing: PricingConfig) -> None:
        self._pricing = pricing

    def estimate(self, issue: str) -> ServiceEstimate | None:
        text = issue.casefold()
        for rule in self._pricing.rules:
            if any(keyword.casefold() in text for keyword in rule.keywords):
                return self._build_estimate(rule)
        return None

    def _build_estimate(self, rule: ServiceRule) -> ServiceEstimate:
        return ServiceEstimate(
            service_name=rule.service_name,
            currency=self._pricing.currency,
            parts=rule.parts,
            labour=LabourEstimate(
                hours=rule.labour_hours,
                hourly_rate=self._pricing.labour_hourly_rate,
            ),
            estimated_duration_hours=rule.duration_hours,
        )