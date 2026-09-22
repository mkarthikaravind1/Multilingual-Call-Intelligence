from decimal import Decimal

import pytest

from app.domain.service_estimate import EstimatedPart, ServiceEstimate
from app.estimation.default_pricing import DEFAULT_PRICING_CONFIG
from app.estimation.pricing_config import PricingConfig, ServiceRule
from app.estimation.provider import ServiceEstimationProvider
from app.estimation.rule_based_provider import RuleBasedEstimationProvider


def make_config(part_price: str = "100", rate: str = "200") -> PricingConfig:
    return PricingConfig(
        currency="USD",
        labour_hourly_rate=Decimal(rate),
        rules=(
            ServiceRule(
                service_name="Tyre Rotation",
                keywords=("tyre", "wheel"),
                parts=(EstimatedPart("Valve", 4, Decimal(part_price)),),
                labour_hours=1.0,
                duration_hours=2.0,
            ),
            ServiceRule(
                service_name="Wheel Alignment",
                keywords=("wheel",),
                parts=(),
                labour_hours=0.5,
                duration_hours=1.0,
            ),
        ),
    )


def test_provider_implements_contract() -> None:
    assert isinstance(RuleBasedEstimationProvider(make_config()), ServiceEstimationProvider)


def test_matches_keyword_case_insensitively_and_builds_estimate() -> None:
    estimate = RuleBasedEstimationProvider(make_config()).estimate("Flat TYRE again")

    assert isinstance(estimate, ServiceEstimate)
    assert estimate.service_name == "Tyre Rotation"
    assert estimate.currency == "USD"
    assert estimate.parts_cost == Decimal("400")
    assert estimate.labour_cost == Decimal("200")
    assert estimate.estimated_cost == Decimal("600")
    assert estimate.estimated_duration_hours == 2.0


def test_pricing_comes_from_injected_config() -> None:
    cheap = RuleBasedEstimationProvider(make_config("10", "50")).estimate("tyre")
    dear = RuleBasedEstimationProvider(make_config("1000", "900")).estimate("tyre")

    assert cheap is not None
    assert cheap.estimated_cost == Decimal("90")
    assert dear is not None
    assert dear.estimated_cost == Decimal("4900")


def test_first_matching_rule_wins() -> None:
    estimate = RuleBasedEstimationProvider(make_config()).estimate("wheel wobble")
    assert estimate is not None
    assert estimate.service_name == "Tyre Rotation"


def test_unknown_issue_returns_none() -> None:
    assert RuleBasedEstimationProvider(make_config()).estimate("sunroof leak") is None


def test_empty_rules_returns_none() -> None:
    config = PricingConfig("INR", Decimal("100"), ())
    assert RuleBasedEstimationProvider(config).estimate("brake") is None


@pytest.mark.parametrize(
    "rule", DEFAULT_PRICING_CONFIG.rules, ids=lambda rule: rule.service_name
)
def test_default_pricing_rules_build_valid_estimates(rule: ServiceRule) -> None:
    estimate = RuleBasedEstimationProvider(DEFAULT_PRICING_CONFIG).estimate(
        rule.keywords[0]
    )

    assert estimate is not None
    assert estimate.service_name == rule.service_name
    assert estimate.currency == DEFAULT_PRICING_CONFIG.currency
    assert estimate.estimated_cost > 0


def test_service_rule_rejects_empty_keywords() -> None:
    with pytest.raises(ValueError):
        ServiceRule("X", (), (), 1.0, 1.0)


def test_service_rule_rejects_blank_keyword() -> None:
    with pytest.raises(ValueError):
        ServiceRule("X", ("brake", " "), (), 1.0, 1.0)


def test_service_rule_rejects_blank_name() -> None:
    with pytest.raises(ValueError):
        ServiceRule(" ", ("brake",), (), 1.0, 1.0)


def test_pricing_config_rejects_blank_currency() -> None:
    with pytest.raises(ValueError):
        PricingConfig(" ", Decimal("100"), ())