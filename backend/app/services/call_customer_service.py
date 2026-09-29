import logging
import threading
import time
from collections.abc import Callable

from app.crm.provider import CrmUnavailableError, CustomerDirectory
from app.domain.call_customer import CallCustomerLink, CallCustomerView, CustomerMatchStatus
from app.domain.customer import CustomerProfile, Vehicle
from app.domain.customer_contact import CustomerContact
from app.domain.phone_number import normalize_phone_number
from app.services.call_customer_repository import CallCustomerRepository

logger = logging.getLogger(__name__)


class InvalidPhoneNumberError(ValueError):
    pass


class VehicleSelectionError(ValueError):
    pass


class CallCustomerService:
    """Links calls to CRM customers.

    The caller's number is stored when the call starts (no CRM call, so the
    telephony webhook stays fast). The CRM is consulted when the customer is
    needed; the first match is remembered on the call, so the link survives
    later changes to the customer's phone number in the CRM.
    """

    def __init__(
        self,
        repository: CallCustomerRepository,
        directory: CustomerDirectory,
        default_country_code: str = "",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._repository = repository
        self._directory = directory
        self._default_country_code = default_country_code
        self._clock = clock
        # Serialises read-modify-write of a link (single-process deployment).
        self._lock = threading.Lock()

    def normalize(self, phone_number: str) -> str:
        """Canonical form of a number typed by a person; raises if unusable."""
        number = normalize_phone_number(phone_number, self._default_country_code)
        if number is None:
            raise InvalidPhoneNumberError(f"{phone_number!r} is not a valid phone number.")
        return number

    def record_caller(self, call_id: str, raw_number: str | None) -> CallCustomerLink:
        """Store the number the call came from. An unusable or withheld
        number is stored as unknown rather than rejected: the call goes on."""
        number = normalize_phone_number(raw_number, self._default_country_code)
        return self._update(
            call_id, caller_number=number, customer_id=None, vehicle_id=None
        )

    def identify(self, call_id: str, phone_number: str) -> CallCustomerView:
        """Set the customer's number by hand (e.g. a withheld caller ID or a
        manual call) and look the customer up again."""
        number = self.normalize(phone_number)
        self._update(call_id, caller_number=number, customer_id=None, vehicle_id=None)
        return self.get(call_id)

    def select_vehicle(self, call_id: str, vehicle_id: str | None) -> CallCustomerView:
        """Choose which of the customer's vehicles the call is about; None
        clears the choice."""
        view = self.get(call_id)
        if vehicle_id is not None:
            if view.status is not CustomerMatchStatus.MATCHED or view.customer is None:
                raise VehicleSelectionError(
                    "A vehicle can only be chosen once the customer is identified."
                )
            if vehicle_id not in {v.vehicle_id for v in view.vehicles}:
                raise VehicleSelectionError(
                    f"Vehicle {vehicle_id!r} does not belong to this customer."
                )
        customer_id = None if view.customer is None else view.customer.customer_id
        self._update(call_id, customer_id=customer_id, vehicle_id=vehicle_id)
        return self.get(call_id)

    def get(self, call_id: str) -> CallCustomerView:
        link = self._repository.get(call_id) or CallCustomerLink(call_id=call_id)

        if not self._directory.is_configured:
            return CallCustomerView(
                call_id, CustomerMatchStatus.CRM_NOT_CONFIGURED, link.caller_number
            )

        try:
            customer = self._find_customer(link)
            if customer is None:
                status = (
                    CustomerMatchStatus.NOT_FOUND
                    if link.caller_number
                    else CustomerMatchStatus.NO_CALLER_NUMBER
                )
                return CallCustomerView(call_id, status, link.caller_number)

            vehicles = self._directory.list_vehicles(customer.customer_id)
            selected = _selected_vehicle(link, vehicles)
            history = (
                self._directory.list_service_history(selected) if selected else ()
            )
        except CrmUnavailableError:
            logger.warning("CRM unavailable while resolving the customer for call %r", call_id)
            return CallCustomerView(
                call_id, CustomerMatchStatus.CRM_UNAVAILABLE, link.caller_number
            )

        return CallCustomerView(
            call_id=call_id,
            status=CustomerMatchStatus.MATCHED,
            caller_number=link.caller_number,
            customer=customer,
            vehicles=vehicles,
            selected_vehicle_id=selected,
            service_history=history,
        )

    def resolve_contact(self, call_id: str) -> CustomerContact | None:
        """The customer's messaging contact for this call, if identified.
        Used for post-call summary delivery."""
        return self.get(call_id).contact

    def _find_customer(self, link: CallCustomerLink) -> CustomerProfile | None:
        if link.customer_id is not None:
            customer = self._directory.get_customer(link.customer_id)
            if customer is not None:
                return customer
        if link.caller_number is None:
            return None
        customer = self._directory.find_by_phone(link.caller_number)
        if customer is not None:
            self._update(link.call_id, customer_id=customer.customer_id)
        return customer

    def _update(self, call_id: str, **changes) -> CallCustomerLink:
        with self._lock:
            current = self._repository.get(call_id) or CallCustomerLink(call_id=call_id)
            updated = current.replace(**changes, updated_at=self._clock())
            self._repository.save(updated)
            return updated


def _selected_vehicle(link: CallCustomerLink, vehicles: tuple[Vehicle, ...]) -> str | None:
    ids = [vehicle.vehicle_id for vehicle in vehicles]
    if link.vehicle_id in ids:
        return link.vehicle_id
    # With a single vehicle there is nothing to choose.
    return ids[0] if len(ids) == 1 else None
