from abc import ABC, abstractmethod

from app.domain.service_estimate import ServiceEstimate

class ServiceEstimationProvider(ABC):
    @abstractmethod
    def estimate(self, issue: str) -> ServiceEstimate | None:
        raise NotImplementedError