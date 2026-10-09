from app.domain.service_estimate import LabourEstimate, ServiceEstimate
from app.estimation.pricing_config import PricingConfig, PricingSource, ServiceRule, pricing_source
from app.estimation.provider import ServiceEstimationProvider


class RuleBasedEstimationProvider(ServiceEstimationProvider):
    def __init__(self, pricing: PricingSource) -> None:
        self._pricing = pricing_source(pricing)

    def estimate(self, issue: str) -> ServiceEstimate | None:
        pricing = self._pricing()
        text = issue.casefold()
        for rule in pricing.rules:
            if any(keyword.casefold() in text for keyword in rule.keywords):
                return build_service_estimate(pricing, rule)
        return None


def build_service_estimate(
    pricing: PricingConfig, rule: ServiceRule, *, approximate: bool = False
) -> ServiceEstimate:
    return ServiceEstimate(
        service_name=rule.service_name,
        currency=pricing.currency,
        parts=rule.parts,
        labour=LabourEstimate(
            hours=rule.labour_hours,
            hourly_rate=pricing.labour_hourly_rate,
            gst_percent=pricing.labour_gst_percent,
        ),
        estimated_duration_hours=rule.duration_hours,
        priced_for_model=rule.vehicle_model,
        approximate=approximate,
    )
