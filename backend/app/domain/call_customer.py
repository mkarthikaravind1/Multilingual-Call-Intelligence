import dataclasses
from dataclasses import dataclass
from enum import Enum

from app.domain.customer import CustomerProfile, ServiceRecord, Vehicle
from app.domain.customer_contact import CustomerContact


def _optional_text(value: str | None, field_name: str) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError(f"{field_name} must not be blank when provided.")


@dataclass(frozen=True)
class CallCustomerLink:
    """Who a call is with: the caller's number and, once the CRM recognised
    it, the customer and the vehicle the call is about. Keyed by call_id.

    customer_name and vehicle_registration are a snapshot of the CRM record
    taken when the customer was resolved, so call lists can show and search
    them without a CRM round trip per call. The CRM stays the source of truth.
    """

    call_id: str
    caller_number: str | None = None
    customer_id: str | None = None
    vehicle_id: str | None = None
    updated_at: float = 0.0
    customer_name: str | None = None
    vehicle_registration: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, str) or not self.call_id.strip():
            raise ValueError("call_id must not be empty.")
        _optional_text(self.caller_number, "caller_number")
        _optional_text(self.customer_id, "customer_id")
        _optional_text(self.vehicle_id, "vehicle_id")
        _optional_text(self.customer_name, "customer_name")
        _optional_text(self.vehicle_registration, "vehicle_registration")
        if self.vehicle_id is not None and self.customer_id is None:
            raise ValueError("A vehicle can only be linked together with its customer.")
        if self.customer_name is not None and self.customer_id is None:
            raise ValueError("A customer name can only be stored together with its customer.")
        # Tied to the customer, not vehicle_id: a customer's only vehicle is
        # selected without being stored on the link.
        if self.vehicle_registration is not None and self.customer_id is None:
            raise ValueError(
                "A vehicle registration can only be stored together with its customer."
            )
        if isinstance(self.updated_at, bool) or not isinstance(self.updated_at, (int, float)):
            raise TypeError("updated_at must be a number.")
        if self.updated_at < 0:
            raise ValueError("updated_at must not be negative.")

    def replace(self, **changes) -> "CallCustomerLink":
        return dataclasses.replace(self, **changes)


class CustomerMatchStatus(str, Enum):
    MATCHED = "matched"
    NOT_FOUND = "not_found"
    NO_CALLER_NUMBER = "no_caller_number"
    CRM_NOT_CONFIGURED = "crm_not_configured"
    CRM_UNAVAILABLE = "crm_unavailable"


@dataclass(frozen=True)
class CallCustomerView:
    """Everything known about the customer on a call, assembled from the
    stored link and a live CRM read."""

    call_id: str
    status: CustomerMatchStatus
    caller_number: str | None
    customer: CustomerProfile | None = None
    vehicles: tuple[Vehicle, ...] = ()
    selected_vehicle_id: str | None = None
    service_history: tuple[ServiceRecord, ...] = ()

    @property
    def contact(self) -> CustomerContact | None:
        return None if self.customer is None else self.customer.to_contact()
