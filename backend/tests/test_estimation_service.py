from decimal import Decimal

import pytest

from app.domain.service_estimate import EstimatedPart, LabourEstimate, ServiceEstimate
from app.estimation.default_pricing import DEFAULT_PRICING_CONFIG
from app.estimation.provider import ServiceEstimationProvider
from app.estimation.rule_based_provider import RuleBasedEstimationProvider
from app.services.estimation_service import EstimationService


def make_estimate() -> ServiceEstimate:
    return ServiceEstimate(
        service_name="Oil Change",
        currency="INR",
        parts=(EstimatedPart("Oil filter", 1, Decimal("300")),),
        labour=LabourEstimate(hours=0.5, hourly_rate=Decimal("600")),
        estimated_duration_hours=1.0,
    )


class FakeProvider(ServiceEstimationProvider):
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.issues: list[str] = []

    def estimate(self, issue: str):
        self.issues.append(issue)
        if self._error is not None:
            raise self._error
        return self._result


def test_returns_provider_estimate_and_strips_issue() -> None:
    estimate = make_estimate()
    provider = FakeProvider(estimate)

    result = EstimationService(provider).estimate("  oil change  ")

    assert result is estimate
    assert provider.issues == ["oil change"]


def test_returns_none_when_provider_has_no_estimate() -> None:
    assert EstimationService(FakeProvider(None)).estimate("sunroof leak") is None


@pytest.mark.parametrize("issue", ["", "   ", None, 5])
def test_rejects_invalid_issue_without_calling_provider(issue) -> None:
    provider = FakeProvider(make_estimate())

    with pytest.raises(ValueError):
        EstimationService(provider).estimate(issue)

    assert provider.issues == []


def test_rejects_invalid_provider_result() -> None:
    with pytest.raises(TypeError):
        EstimationService(FakeProvider({"cost": 100})).estimate("oil change")


def test_provider_exceptions_propagate() -> None:
    with pytest.raises(RuntimeError, match="pricing offline"):
        EstimationService(FakeProvider(error=RuntimeError("pricing offline"))).estimate(
            "oil change"
        )


def test_end_to_end_with_rule_based_provider_and_default_pricing() -> None:
    service = EstimationService(RuleBasedEstimationProvider(DEFAULT_PRICING_CONFIG))

    estimate = service.estimate("My brakes are making noise")

    assert estimate is not None
    assert estimate.service_name == "Brake Pad Replacement"
    assert estimate.estimated_cost == Decimal("3700")
    assert estimate.estimated_duration_hours == 3.0