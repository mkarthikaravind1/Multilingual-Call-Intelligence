from abc import ABC, abstractmethod

from app.domain.customer_summary_delivery import CustomerSummaryDelivery


class CustomerSummaryDeliveryRepository(ABC):
    @abstractmethod
    def save(self, delivery: CustomerSummaryDelivery) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_by_call_id(self, call_id: str) -> tuple[CustomerSummaryDelivery, ...]:
        raise NotImplementedError

    @abstractmethod
    def get_by_idempotency_key(self, idempotency_key: str) -> CustomerSummaryDelivery | None:
        raise NotImplementedError

    @abstractmethod
    def get_latest_by_call_id(self, call_id: str) -> CustomerSummaryDelivery | None:
        raise NotImplementedError


class InMemoryCustomerSummaryDeliveryRepository(CustomerSummaryDeliveryRepository):
    def __init__(self) -> None:
        self._deliveries: dict[str, list[CustomerSummaryDelivery]] = {}
        self._by_idempotency: dict[str, CustomerSummaryDelivery] = {}

    def save(self, delivery: CustomerSummaryDelivery) -> None:
        if delivery.idempotency_key is not None:
            self._by_idempotency[delivery.idempotency_key] = delivery
        self._deliveries.setdefault(delivery.call_id, []).append(delivery)

    def get_by_call_id(self, call_id: str) -> tuple[CustomerSummaryDelivery, ...]:
        return tuple(self._deliveries.get(call_id, ()))

    def get_by_idempotency_key(self, idempotency_key: str) -> CustomerSummaryDelivery | None:
        return self._by_idempotency.get(idempotency_key)

    def get_latest_by_call_id(self, call_id: str) -> CustomerSummaryDelivery | None:
        deliveries = self._deliveries.get(call_id, ())
        return None if not deliveries else deliveries[-1]
