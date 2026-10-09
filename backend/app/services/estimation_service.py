from collections.abc import Sequence

from app.domain.service_estimate import CallServiceEstimate, ServiceEstimate
from app.domain.utterance import Utterance
from app.estimation.default_pricing import DEFAULT_PRICING_CONFIG
from app.estimation.detection import KeywordServiceDetector, ServiceDetectionProvider
from app.estimation.pricing_config import PricingSource, pricing_source
from app.estimation.provider import ServiceEstimationProvider
from app.estimation.rule_based_provider import build_service_estimate


class EstimationService:
    def __init__(
        self,
        provider: ServiceEstimationProvider,
        pricing: PricingSource | None = None,
        detector: ServiceDetectionProvider | None = None,
    ) -> None:
        self._provider = provider
        self._pricing = pricing_source(pricing or DEFAULT_PRICING_CONFIG)
        self._detector = detector or KeywordServiceDetector(self._pricing)

    def estimate(self, issue: str) -> ServiceEstimate | None:
        if not isinstance(issue, str) or not issue.strip():
            raise ValueError("issue must not be empty.")

        result = self._provider.estimate(issue.strip())
        if result is not None and not isinstance(result, ServiceEstimate):
            raise TypeError("Estimation provider returned an invalid result.")
        return result

    def estimate_call(
        self, utterances: Sequence[Utterance], vehicle_model: str | None = None
    ) -> CallServiceEstimate | None:
        """Every service the call has needed so far, priced from the price
        list and added up. Reading the whole call, the estimate stays (and
        grows) until the call ends. None when no service came up.

        Prices are for vehicle_model (the caller's vehicle, from the CRM),
        else for the model named in the call; a service without a price for
        that model gets its all-models price, marked approximate."""
        if not utterances:
            return None
        pricing = self._pricing()
        detection = self._detector.detect_call(utterances)
        model = (vehicle_model or "").strip() or detection.vehicle_model
        priced = [
            found for name in detection.services if (found := pricing.price_for(name, model))
        ]
        covered = {
            covered_name.casefold() for found in priced for covered_name in found.rule.covers
        }
        services = tuple(
            build_service_estimate(pricing, found.rule, approximate=found.approximate)
            for found in priced
            if found.rule.service_name.casefold() not in covered
        )
        if not services:
            return None
        return CallServiceEstimate(
            currency=pricing.currency, services=services, vehicle_model=model
        )
