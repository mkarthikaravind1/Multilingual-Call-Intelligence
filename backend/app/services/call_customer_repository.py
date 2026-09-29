import threading
from abc import ABC, abstractmethod

from app.domain.call_customer import CallCustomerLink


class CallCustomerRepository(ABC):
    @abstractmethod
    def get(self, call_id: str) -> CallCustomerLink | None:
        raise NotImplementedError

    @abstractmethod
    def save(self, link: CallCustomerLink) -> None:
        """Insert or update the link for link.call_id."""
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
