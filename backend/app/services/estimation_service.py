from collections.abc import Sequence

from app.domain.service_estimate import CallServiceEstimate, ServiceEstimate
from app.domain.utterance import Utterance
from app.estimation.default_pricing import DEFAULT_PRICING_CONFIG
from app.estimation.detection import KeywordServiceDetector, ServiceDetectionProvider
from app.estimation.pricing_config import PricingConfig
from app.estimation.provider import ServiceEstimationProvider
from app.estimation.rule_based_provider import build_service_estimate


class EstimationService:
    def __init__(
        self,
        provider: ServiceEstimationProvider,
        pricing: PricingConfig | None = None,
        detector: ServiceDetectionProvider | None = None,
    ) -> None:
        self._provider = provider
        self._pricing = pricing or DEFAULT_PRICING_CONFIG
        self._detector = detector or KeywordServiceDetector(self._pricing)

    def estimate(self, issue: str) -> ServiceEstimate | None:
        if not isinstance(issue, str) or not issue.strip():
            raise ValueError("issue must not be empty.")

        result = self._provider.estimate(issue.strip())
        if result is not None and not isinstance(result, ServiceEstimate):
            raise TypeError("Estimation provider returned an invalid result.")
        return result

    def estimate_call(self, utterances: Sequence[Utterance]) -> CallServiceEstimate | None:
        """Every service the call has needed so far, priced from the price
        list and added up. Reading the whole call, the estimate stays (and
        grows) until the call ends. None when no service came up."""
        if not utterances:
            return None
        names = self._detector.detect(utterances)
        rules = [rule for name in names if (rule := self._pricing.rule_for(name)) is not None]
        covered = {
            covered_name.casefold() for rule in rules for covered_name in rule.covers
        }
        services = tuple(
            build_service_estimate(self._pricing, rule)
            for rule in rules
            if rule.service_name.casefold() not in covered
        )
        if not services:
            return None
        return CallServiceEstimate(currency=self._pricing.currency, services=services)
