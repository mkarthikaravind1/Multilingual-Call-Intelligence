import logging
import threading
import time
from collections.abc import Callable, Iterable

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
    later changes to the customer's phone number in the CRM. Each lookup
    also refreshes the customer name and vehicle registration stored on the
    link, which call lists show and search.
    """

    def __init__(
        self,
        repository: CallCustomerRepository,
        directory: CustomerDirectory,
        default_country_code: str = "",
        clock: Callable[[], float] = time.time,
        vehicle_model_cache_seconds: float = 30.0,
    ) -> None:
        self._repository = repository
        self._directory = directory
        self._default_country_code = default_country_code
        self._clock = clock
        # Serialises read-modify-write of a link (single-process deployment).
        self._lock = threading.Lock()
        # call_id -> (good until, vehicle model). The live estimate asks
        # for the model on every new line of speech; without this each
        # one is a full CRM read. Dropped when the call's customer or
        # vehicle is changed here.
        self._vehicle_model_cache_seconds = vehicle_model_cache_seconds
        self._vehicle_models: dict[str, tuple[float, str | None]] = {}

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
        return self._change(call_id, caller_number=number, **_NO_CUSTOMER)

    def identify(
        self, call_id: str, phone_number: str, changed_by: str | None = None
    ) -> CallCustomerView:
        """Set the customer's number by hand (e.g. a withheld caller ID or a
        manual call) and look the customer up again. changed_by: the
        user doing it, for the log."""
        number = self.normalize(phone_number)
        before = self._repository.get(call_id)
        self._change(call_id, caller_number=number, **_NO_CUSTOMER)
        view = self.get(call_id)
        # Who a call is with decides whose history its complaints join
        # and who is texted its summary: keep a trace of every change.
        logger.info(
            "Customer of call %r set by hand by user %r: number %s -> %s, "
            "customer %r -> %r (%s)",
            call_id,
            changed_by,
            _masked(None if before is None else before.caller_number),
            _masked(number),
            None if before is None else before.customer_id,
            None if view.customer is None else view.customer.customer_id,
            view.status.value,
        )
        return view

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
        if view.customer is None:
            self._change(call_id, **_NO_CUSTOMER)
        else:
            # get() below stores the new vehicle's registration.
            self._change(call_id, customer_id=view.customer.customer_id, vehicle_id=vehicle_id)
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
            self._store_snapshot(link, customer, vehicles, selected)
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

    def resolve_contact_for_delivery(self, call_id: str) -> CustomerContact | None:
        """Like resolve_contact, but raises CrmUnavailableError when the
        CRM could not be asked: "no customer" then means there is none,
        and an outage can be retried instead of losing the message."""
        view = self.get(call_id)
        if view.status is CustomerMatchStatus.CRM_UNAVAILABLE:
            raise CrmUnavailableError(f"CRM unavailable for call {call_id!r}")
        return view.contact

    def resolve_customer_id(self, call_id: str) -> str | None:
        """The CRM id of the customer on this call, if identified."""
        customer = self.get(call_id).customer
        return None if customer is None else customer.customer_id

    def resolve_vehicle_model(self, call_id: str) -> str | None:
        """The model ("make model", e.g. "Maruti Swift") of the vehicle the
        call is about, if the CRM knows it. Used to price the estimate."""
        now = self._clock()
        cached = self._vehicle_models.get(call_id)
        if cached is not None and now < cached[0]:
            return cached[1]
        view = self.get(call_id)
        vehicle = next(
            (v for v in view.vehicles if v.vehicle_id == view.selected_vehicle_id), None
        )
        model = None if vehicle is None else f"{vehicle.make} {vehicle.model}"
        if self._vehicle_model_cache_seconds > 0:
            if len(self._vehicle_models) >= _VEHICLE_MODEL_CACHE_SIZE:
                self._vehicle_models = {
                    key: entry for key, entry in self._vehicle_models.items() if now < entry[0]
                }
            self._vehicle_models[call_id] = (now + self._vehicle_model_cache_seconds, model)
        return model

    def stored_links(self, call_ids: Iterable[str]) -> dict[str, CallCustomerLink]:
        """Who each call was with, as last stored (the customer name and
        vehicle snapshot included); no CRM lookup."""
        return self._repository.get_many(call_ids)

    def refresh_customer_names(self) -> tuple[int, int]:
        """Look up every linked call that has no customer name stored yet
        (calls from before names were stored, or whose customer was never
        looked up). Returns (calls named now, calls checked)."""
        links = self._repository.list_without_customer_name()
        named = 0
        for link in links:
            if self.get(link.call_id).customer is not None:
                named += 1
        return named, len(links)

    def _find_customer(self, link: CallCustomerLink) -> CustomerProfile | None:
        # The match is stored on the link by _store_snapshot.
        if link.customer_id is not None:
            customer = self._directory.get_customer(link.customer_id)
            if customer is not None:
                return customer
        if link.caller_number is None:
            return None
        return self._directory.find_by_phone(link.caller_number)

    def _store_snapshot(
        self,
        link: CallCustomerLink,
        customer: CustomerProfile,
        vehicles: tuple[Vehicle, ...],
        selected_vehicle_id: str | None,
    ) -> None:
        registration = next(
            (v.registration_number for v in vehicles if v.vehicle_id == selected_vehicle_id),
            None,
        )
        snapshot = (customer.customer_id, customer.name, registration)
        if (link.customer_id, link.customer_name, link.vehicle_registration) == snapshot:
            return
        with self._lock:
            current = self._repository.get(link.call_id) or CallCustomerLink(call_id=link.call_id)
            if current.caller_number != link.caller_number:
                # The number was changed while the CRM was being asked:
                # this customer belongs to the old number. Storing them
                # would undo the change, and they would then stick.
                return
            self._repository.save(
                current.replace(
                    customer_id=customer.customer_id,
                    customer_name=customer.name,
                    vehicle_registration=registration,
                    updated_at=self._clock(),
                )
            )

    def _change(self, call_id: str, **changes) -> CallCustomerLink:
        """A change to who the call is with or which vehicle it is about."""
        self._vehicle_models.pop(call_id, None)
        return self._update(call_id, **changes)

    def _update(self, call_id: str, **changes) -> CallCustomerLink:
        with self._lock:
            current = self._repository.get(call_id) or CallCustomerLink(call_id=call_id)
            updated = current.replace(**changes, updated_at=self._clock())
            self._repository.save(updated)
            return updated


_VEHICLE_MODEL_CACHE_SIZE = 1000


def _masked(number: str | None) -> str:
    """A phone number for the log: its last four digits only."""
    return "none" if number is None else f"...{number[-4:]}"


_NO_CUSTOMER = {
    "customer_id": None,
    "vehicle_id": None,
    "customer_name": None,
    "vehicle_registration": None,
}


def _selected_vehicle(link: CallCustomerLink, vehicles: tuple[Vehicle, ...]) -> str | None:
    ids = [vehicle.vehicle_id for vehicle in vehicles]
    if link.vehicle_id in ids:
        return link.vehicle_id
    # With a single vehicle there is nothing to choose.
    return ids[0] if len(ids) == 1 else None
