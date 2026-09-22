from decimal import Decimal

from app.domain.service_estimate import EstimatedPart
from app.estimation.pricing_config import PricingConfig, ServiceRule

DEFAULT_PRICING_CONFIG = PricingConfig(
    currency="INR",
    labour_hourly_rate=Decimal("600"),
    rules=(
        ServiceRule(
            service_name="General Service",
            keywords=("general service", "periodic service", "full service"),
            parts=(
                EstimatedPart("Engine oil (1 L)", 4, Decimal("550")),
                EstimatedPart("Oil filter", 1, Decimal("350")),
                EstimatedPart("Air filter", 1, Decimal("450")),
            ),
            labour_hours=3.0,
            duration_hours=6.0,
        ),
        ServiceRule(
            service_name="Oil Change",
            keywords=("oil change", "engine oil", "oil service"),
            parts=(
                EstimatedPart("Engine oil (1 L)", 4, Decimal("550")),
                EstimatedPart("Oil filter", 1, Decimal("350")),
            ),
            labour_hours=0.5,
            duration_hours=1.0,
        ),
        ServiceRule(
            service_name="Brake Pad Replacement",
            keywords=("brake",),
            parts=(EstimatedPart("Brake pad set", 1, Decimal("2800")),),
            labour_hours=1.5,
            duration_hours=3.0,
        ),
        ServiceRule(
            service_name="Battery Replacement",
            keywords=("battery",),
            parts=(EstimatedPart("Battery", 1, Decimal("5500")),),
            labour_hours=0.5,
            duration_hours=1.0,
        ),
    ),
)