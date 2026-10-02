import threading
from abc import ABC, abstractmethod
from collections.abc import Iterable

from app.domain.call_customer import CallCustomerLink


class CallCustomerRepository(ABC):
    @abstractmethod
    def get(self, call_id: str) -> CallCustomerLink | None:
        raise NotImplementedError

    @abstractmethod
    def save(self, link: CallCustomerLink) -> None:
        """Insert or update the link for link.call_id."""
        raise NotImplementedError

    @abstractmethod
    def get_many(self, call_ids: Iterable[str]) -> dict[str, CallCustomerLink]:
        """The stored links of these calls; calls without one are left out."""
        raise NotImplementedError

    @abstractmethod
    def list_without_customer_name(self) -> tuple[CallCustomerLink, ...]:
        """Links that could name a customer (a caller number or customer id
        is known) but have no customer name stored yet."""
        raise NotImplementedError


class InMemoryCallCustomerRepository(CallCustomerRepository):
    def __init__(self) -> None:
        self._links: dict[str, CallCustomerLink] = {}
        self._lock = threading.Lock()

    def get(self, call_id: str) -> CallCustomerLink | None:
        return self._links.get(call_id)

    def save(self, link: CallCustomerLink) -> None:
        with self._lock:
            self._links[link.call_id] = link

    def get_many(self, call_ids: Iterable[str]) -> dict[str, CallCustomerLink]:
        return {cid: self._links[cid] for cid in call_ids if cid in self._links}

    def list_without_customer_name(self) -> tuple[CallCustomerLink, ...]:
        return tuple(
            link
            for link in self._links.values()
            if link.customer_name is None
            and (link.caller_number is not None or link.customer_id is not None)
        )
