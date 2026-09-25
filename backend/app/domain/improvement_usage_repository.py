from abc import ABC, abstractmethod

from app.domain.improvement_usage import ImprovementUsage


class ImprovementUsageRepository(ABC):

    @abstractmethod
    def save(self, usage: ImprovementUsage) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, usage_id: str) -> ImprovementUsage | None:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> tuple[ImprovementUsage, ...]:
        raise NotImplementedError

    @abstractmethod
    def list_for_improvement(
        self,
        improvement_id: str,
    ) -> tuple[ImprovementUsage, ...]:
        raise NotImplementedError

    @abstractmethod
    def list_for_call(
        self,
        call_id: str,
    ) -> tuple[ImprovementUsage, ...]:
        raise NotImplementedError


class InMemoryImprovementUsageRepository(ImprovementUsageRepository):

    def __init__(self) -> None:
        self._usages: dict[str, ImprovementUsage] = {}

    def save(self, usage: ImprovementUsage) -> None:
        self._usages[usage.usage_id] = usage

    def get(self, usage_id: str) -> ImprovementUsage | None:
        return self._usages.get(usage_id)

    def list_all(self) -> tuple[ImprovementUsage, ...]:
        return tuple(self._usages.values())

    def list_for_improvement(
        self,
        improvement_id: str,
    ) -> tuple[ImprovementUsage, ...]:
        return tuple(
            usage
            for usage in self._usages.values()
            if usage.improvement_id == improvement_id
        )

    def list_for_call(
        self,
        call_id: str,
    ) -> tuple[ImprovementUsage, ...]:
        return tuple(
            usage
            for usage in self._usages.values()
            if usage.call_id == call_id
        )