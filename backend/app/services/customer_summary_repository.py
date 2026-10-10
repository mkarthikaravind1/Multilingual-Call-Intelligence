import threading
from abc import ABC, abstractmethod
from dataclasses import replace

from app.domain.customer_summary_delivery import CustomerSummaryDelivery, DeliveryStatus

_UNFINISHED = (DeliveryStatus.FAILED, DeliveryStatus.QUEUED)


class CustomerSummaryDeliveryRepository(ABC):
    @abstractmethod
    def save(self, delivery: CustomerSummaryDelivery) -> None:
        """Store the delivery, replacing the one with the same delivery_id."""
        raise NotImplementedError

    @abstractmethod
    def add_if_absent(self, delivery: CustomerSummaryDelivery) -> bool:
        """Store a new delivery unless one with its idempotency key exists.
        False when it exists (nothing is stored)."""
        raise NotImplementedError

    @abstractmethod
    def claim_retry(self, delivery_id: str, attempts: int, now: float) -> bool:
        """Mark a failed (or interrupted) delivery queued for another
        attempt, if it is still unfinished with this many attempts. False
        when another run got there first."""
        raise NotImplementedError

    @abstractmethod
    def list_unfinished(
        self, limit: int, max_attempts: int | None = None, created_after: float | None = None
    ) -> tuple[CustomerSummaryDelivery, ...]:
        """Failed and queued deliveries, the longest untouched first.
        max_attempts / created_after leave out those attempted that
        often already, or created at or before that time: they can
        never be tried again, and must not use up the limit."""
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
        self._lock = threading.Lock()
        # delivery_id -> delivery, in the order first stored.
        self._deliveries: dict[str, CustomerSummaryDelivery] = {}

    def save(self, delivery: CustomerSummaryDelivery) -> None:
        with self._lock:
            self._deliveries[delivery.delivery_id] = delivery

    def add_if_absent(self, delivery: CustomerSummaryDelivery) -> bool:
        with self._lock:
            if any(
                stored.idempotency_key == delivery.idempotency_key
                for stored in self._deliveries.values()
            ):
                return False
            self._deliveries[delivery.delivery_id] = delivery
            return True

    def claim_retry(self, delivery_id: str, attempts: int, now: float) -> bool:
        with self._lock:
            stored = self._deliveries.get(delivery_id)
            if stored is None or stored.status not in _UNFINISHED or stored.attempts != attempts:
                return False
            self._deliveries[delivery_id] = replace(
                stored, status=DeliveryStatus.QUEUED, attempts=attempts + 1, updated_at=now
            )
            return True

    def list_unfinished(
        self, limit: int, max_attempts: int | None = None, created_after: float | None = None
    ) -> tuple[CustomerSummaryDelivery, ...]:
        with self._lock:
            unfinished = [
                d
                for d in self._deliveries.values()
                if d.status in _UNFINISHED
                and (max_attempts is None or d.attempts < max_attempts)
                and (created_after is None or d.created_at > created_after)
            ]
        return tuple(sorted(unfinished, key=lambda d: d.updated_at)[:limit])

    def get_by_call_id(self, call_id: str) -> tuple[CustomerSummaryDelivery, ...]:
        with self._lock:
            return tuple(d for d in self._deliveries.values() if d.call_id == call_id)

    def get_by_idempotency_key(self, idempotency_key: str) -> CustomerSummaryDelivery | None:
        with self._lock:
            return next(
                (d for d in self._deliveries.values() if d.idempotency_key == idempotency_key),
                None,
            )

    def get_latest_by_call_id(self, call_id: str) -> CustomerSummaryDelivery | None:
        deliveries = self.get_by_call_id(call_id)
        return None if not deliveries else max(deliveries, key=lambda d: d.updated_at)
