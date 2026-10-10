"""A CustomerDirectory read from a JSON file, for development and pilots
before a real CRM is connected.

A file that cannot be read at all fails loudly at startup. A single invalid
customer is skipped and reported (see problems) rather than taking every
other customer down with it. The file is read again when it changes, so an
edit (a new customer, consent withdrawn) needs no restart.

Format:
{
  "customers": [
    {
      "customer_id": "C-1001",
      "name": "...",
      "phone_number": "+91 98765 43210",
      "email": null,
      "preferred_channel": "sms",
      "consent_status": "granted",
      "language": "hi",
      "vehicles": [
        {
          "vehicle_id": "V-2001",
          "registration_number": "KA01AB1234",
          "make": "...", "model": "...", "year": 2021, "vin": null,
          "service_history": [
            {"service_id": "S-1", "service_date": "2026-08-02",
             "description": "...", "dealer": "...", "odometer_km": 20000}
          ]
        }
      ]
    }
  ]
}
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.crm.provider import CustomerDirectory
from app.domain.customer import CustomerProfile, ServiceRecord, Vehicle
from app.domain.customer_contact import ConsentStatus, MessagingChannel
from app.domain.phone_number import normalize_phone_number

logger = logging.getLogger(__name__)

# How often, at most, the file is checked for a change.
RELOAD_CHECK_SECONDS = 5.0
_MAX_LOGGED_PROBLEMS = 20


class CrmDataError(ValueError):
    pass


@dataclass
class _Customers:
    """One reading of the file."""

    customers: dict[str, CustomerProfile] = field(default_factory=dict)
    # A number two customers share maps to None: the caller could be either,
    # so nobody is matched automatically and the agent identifies them.
    by_phone: dict[str, str | None] = field(default_factory=dict)
    vehicles: dict[str, tuple[Vehicle, ...]] = field(default_factory=dict)
    history: dict[str, tuple[ServiceRecord, ...]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


class JsonFileCustomerDirectory(CustomerDirectory):
    def __init__(
        self,
        path: str | Path,
        default_country_code: str = "",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._path = Path(path)
        self._default_country_code = default_country_code
        self._clock = clock
        self._reload_lock = threading.Lock()
        self._stamp = self._file_stamp()
        # The stamp of a changed file that could not be read, so the same
        # broken file is reported once, not at every check.
        self._unreadable_stamp: tuple[int, int] | None = None
        self._data = self._load()
        self._next_check = clock() + RELOAD_CHECK_SECONDS

    @property
    def problems(self) -> tuple[str, ...]:
        """What was skipped or left unmatched in the file as last read."""
        return tuple(self._current().problems)

    @property
    def customer_count(self) -> int:
        return len(self._current().customers)

    def find_by_phone(self, phone_number: str) -> CustomerProfile | None:
        data = self._current()
        customer_id = data.by_phone.get(phone_number)
        return None if customer_id is None else data.customers[customer_id]

    def get_customer(self, customer_id: str) -> CustomerProfile | None:
        return self._current().customers.get(customer_id)

    def list_vehicles(self, customer_id: str) -> tuple[Vehicle, ...]:
        return self._current().vehicles.get(customer_id, ())

    def list_service_history(self, vehicle_id: str) -> tuple[ServiceRecord, ...]:
        return self._current().history.get(vehicle_id, ())

    # --- Reading the file ---

    def _current(self) -> _Customers:
        """The customers, read again first if the file has changed."""
        if self._clock() < self._next_check:
            return self._data
        with self._reload_lock:
            if self._clock() < self._next_check:
                return self._data
            self._next_check = self._clock() + RELOAD_CHECK_SECONDS
            stamp = self._file_stamp()
            if stamp == self._stamp or stamp == self._unreadable_stamp:
                return self._data
            try:
                self._data = self._load()
            except CrmDataError as exc:
                # e.g. caught half-written: keep what we have until it
                # changes again.
                logger.error("CRM file changed but could not be read; keeping the old data: %s", exc)
                self._unreadable_stamp = stamp
                return self._data
            self._stamp = stamp
            self._unreadable_stamp = None
            logger.info("CRM file read again: %d customers", len(self._data.customers))
            return self._data

    def _file_stamp(self) -> tuple[int, int] | None:
        try:
            stat = self._path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _load(self) -> _Customers:
        try:
            raw_data = json.loads(self._path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise CrmDataError(f"Cannot read CRM file {str(self._path)!r}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise CrmDataError(f"CRM file {str(self._path)!r} is not valid JSON: {exc}") from exc
        if not isinstance(raw_data, dict) or not isinstance(raw_data.get("customers"), list):
            raise CrmDataError("CRM file must be an object with a 'customers' list.")

        data = _Customers()
        rows = raw_data["customers"]
        for index, raw in enumerate(rows):
            try:
                _add_customer(data, raw, self._default_country_code)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                data.problems.append(f"Invalid customer at index {index}: {exc}")
        if rows and not data.customers:
            raise CrmDataError(f"CRM file has no usable customer. {data.problems[0]}")

        for problem in data.problems[:_MAX_LOGGED_PROBLEMS]:
            logger.warning("CRM file: %s", problem)
        if len(data.problems) > _MAX_LOGGED_PROBLEMS:
            logger.warning(
                "CRM file: %d more problems not shown", len(data.problems) - _MAX_LOGGED_PROBLEMS
            )
        return data


def _add_customer(data: _Customers, raw: dict[str, Any], default_country_code: str) -> None:
    """Add one customer with their vehicles, or raise and add nothing."""
    phone = normalize_phone_number(raw["phone_number"], default_country_code)
    if phone is None:
        raise ValueError("unusable phone_number")
    customer = CustomerProfile(
        customer_id=raw["customer_id"],
        name=raw["name"],
        phone_number=phone,
        email=raw.get("email"),
        preferred_channel=MessagingChannel(raw.get("preferred_channel", "sms")),
        consent_status=ConsentStatus(raw.get("consent_status", "unknown")),
        language=raw.get("language"),
    )
    if customer.customer_id in data.customers:
        raise ValueError(f"duplicate customer_id {customer.customer_id!r}")

    vehicles: list[Vehicle] = []
    histories: dict[str, tuple[ServiceRecord, ...]] = {}
    for raw_vehicle in raw.get("vehicles", []):
        vehicle = Vehicle(
            vehicle_id=raw_vehicle["vehicle_id"],
            customer_id=customer.customer_id,
            registration_number=raw_vehicle["registration_number"],
            make=raw_vehicle["make"],
            model=raw_vehicle["model"],
            year=raw_vehicle.get("year"),
            vin=raw_vehicle.get("vin"),
        )
        if vehicle.vehicle_id in data.history or vehicle.vehicle_id in histories:
            raise ValueError(f"duplicate vehicle_id {vehicle.vehicle_id!r}")
        history = [
            ServiceRecord(
                service_id=record["service_id"],
                vehicle_id=vehicle.vehicle_id,
                service_date=record["service_date"],
                description=record["description"],
                dealer=record.get("dealer"),
                odometer_km=record.get("odometer_km"),
            )
            for record in raw_vehicle.get("service_history", [])
        ]
        histories[vehicle.vehicle_id] = tuple(
            sorted(history, key=lambda r: r.service_date, reverse=True)
        )
        vehicles.append(vehicle)

    data.customers[customer.customer_id] = customer
    data.vehicles[customer.customer_id] = tuple(vehicles)
    data.history.update(histories)

    if phone not in data.by_phone:
        data.by_phone[phone] = customer.customer_id
        return
    other = data.by_phone[phone]
    data.by_phone[phone] = None
    data.problems.append(
        f"Customer {customer.customer_id!r} shares a phone number with "
        f"{'other customers' if other is None else repr(other)}: callers from it "
        "are not matched automatically"
    )
