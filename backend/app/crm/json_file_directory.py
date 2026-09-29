"""A CustomerDirectory read from a JSON file, for development and pilots
before a real CRM is connected. The file is loaded and validated once at
startup; a bad file fails loudly instead of silently matching nobody.

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
from pathlib import Path
from typing import Any

from app.crm.provider import CustomerDirectory
from app.domain.customer import CustomerProfile, ServiceRecord, Vehicle
from app.domain.customer_contact import ConsentStatus, MessagingChannel
from app.domain.phone_number import normalize_phone_number


class CrmDataError(ValueError):
    pass


class JsonFileCustomerDirectory(CustomerDirectory):
    def __init__(self, path: str | Path, default_country_code: str = "") -> None:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise CrmDataError(f"Cannot read CRM file {str(path)!r}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise CrmDataError(f"CRM file {str(path)!r} is not valid JSON: {exc}") from exc

        self._customers: dict[str, CustomerProfile] = {}
        self._by_phone: dict[str, str] = {}
        self._vehicles: dict[str, tuple[Vehicle, ...]] = {}
        self._history: dict[str, tuple[ServiceRecord, ...]] = {}

        if not isinstance(data, dict) or not isinstance(data.get("customers"), list):
            raise CrmDataError("CRM file must be an object with a 'customers' list.")
        for index, raw in enumerate(data["customers"]):
            try:
                self._load_customer(raw, default_country_code)
            except (KeyError, TypeError, ValueError) as exc:
                raise CrmDataError(f"Invalid customer at index {index}: {exc}") from exc

    def _load_customer(self, raw: dict[str, Any], default_country_code: str) -> None:
        phone = normalize_phone_number(raw["phone_number"], default_country_code)
        if phone is None:
            raise ValueError(f"unusable phone_number {raw['phone_number']!r}")
        customer = CustomerProfile(
            customer_id=raw["customer_id"],
            name=raw["name"],
            phone_number=phone,
            email=raw.get("email"),
            preferred_channel=MessagingChannel(raw.get("preferred_channel", "sms")),
            consent_status=ConsentStatus(raw.get("consent_status", "unknown")),
            language=raw.get("language"),
        )
        if customer.customer_id in self._customers:
            raise ValueError(f"duplicate customer_id {customer.customer_id!r}")
        if phone in self._by_phone:
            raise ValueError(f"phone number {phone} belongs to two customers")

        vehicles = []
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
            if vehicle.vehicle_id in self._history:
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
            self._history[vehicle.vehicle_id] = tuple(
                sorted(history, key=lambda r: r.service_date, reverse=True)
            )
            vehicles.append(vehicle)

        self._customers[customer.customer_id] = customer
        self._by_phone[phone] = customer.customer_id
        self._vehicles[customer.customer_id] = tuple(vehicles)

    def find_by_phone(self, phone_number: str) -> CustomerProfile | None:
        customer_id = self._by_phone.get(phone_number)
        return None if customer_id is None else self._customers[customer_id]

    def get_customer(self, customer_id: str) -> CustomerProfile | None:
        return self._customers.get(customer_id)

    def list_vehicles(self, customer_id: str) -> tuple[Vehicle, ...]:
        return self._vehicles.get(customer_id, ())

    def list_service_history(self, vehicle_id: str) -> tuple[ServiceRecord, ...]:
        return self._history.get(vehicle_id, ())
