"""The CRM boundary: the only way the application reads customer and vehicle
data. A real CRM (dealer DMS, Salesforce, ...) is added as another
CustomerDirectory implementation; nothing else in the app knows which CRM
is behind it."""

from abc import ABC, abstractmethod

from app.domain.customer import CustomerProfile, ServiceRecord, Vehicle


class CrmUnavailableError(Exception):
    """The CRM could not be reached or answered with an error. Callers treat
    it as "unknown right now", never as "customer does not exist"."""


class CustomerDirectory(ABC):
    # False only for the placeholder used when no CRM is connected.
    is_configured: bool = True

    @abstractmethod
    def find_by_phone(self, phone_number: str) -> CustomerProfile | None:
        """Look up a customer by a normalised phone number (see
        app.domain.phone_number). None means the CRM has no such customer."""
        raise NotImplementedError

    @abstractmethod
    def get_customer(self, customer_id: str) -> CustomerProfile | None:
        raise NotImplementedError

    @abstractmethod
    def list_vehicles(self, customer_id: str) -> tuple[Vehicle, ...]:
        raise NotImplementedError

    @abstractmethod
    def list_service_history(self, vehicle_id: str) -> tuple[ServiceRecord, ...]:
        """Most recent first."""
        raise NotImplementedError


class NoCustomerDirectory(CustomerDirectory):
    """Used when no CRM is connected: every lookup finds nothing."""

    is_configured = False

    def find_by_phone(self, phone_number: str) -> CustomerProfile | None:
        return None

    def get_customer(self, customer_id: str) -> CustomerProfile | None:
        return None

    def list_vehicles(self, customer_id: str) -> tuple[Vehicle, ...]:
        return ()

    def list_service_history(self, vehicle_id: str) -> tuple[ServiceRecord, ...]:
        return ()
