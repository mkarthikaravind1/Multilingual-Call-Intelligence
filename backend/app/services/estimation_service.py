from app.domain.service_estimate import ServiceEstimate
from app.estimation.provider import ServiceEstimationProvider


class EstimationService:
    def __init__(self, provider: ServiceEstimationProvider) -> None:
        self._provider = provider

    def estimate(self, issue: str) -> ServiceEstimate | None:
        if not isinstance(issue, str) or not issue.strip():
            raise ValueError("issue must not be empty.")

        result = self._provider.estimate(issue.strip())
        if result is not None and not isinstance(result, ServiceEstimate):
            raise TypeError("Estimation provider returned an invalid result.")
        return result