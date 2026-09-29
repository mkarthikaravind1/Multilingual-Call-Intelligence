"""Customer and vehicle records as the CRM describes them. The CRM stays the
source of truth; the application only reads these and links a call to a
customer by id."""

from dataclasses import dataclass

from app.domain.customer_contact import ConsentStatus, CustomerContact, MessagingChannel


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


def _optional_text(value: str | None, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


@dataclass(frozen=True)
class ServiceRecord:
    service_id: str
    vehicle_id: str
    service_date: str  # ISO date (YYYY-MM-DD) as the CRM reports it
    description: str
    dealer: str | None = None
    odometer_km: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.service_id, "service_id")
        _require_text(self.vehicle_id, "vehicle_id")
        _require_text(self.service_date, "service_date")
        _require_text(self.description, "description")
        _optional_text(self.dealer, "dealer")
        if self.odometer_km is not None and (
            isinstance(self.odometer_km, bool)
            or not isinstance(self.odometer_km, int)
            or self.odometer_km < 0
        ):
            raise ValueError("odometer_km must be a non-negative integer.")


@dataclass(frozen=True)
class Vehicle:
    vehicle_id: str
    customer_id: str
    registration_number: str
    make: str
    model: str
    year: int | None = None
    vin: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.vehicle_id, "vehicle_id")
        _require_text(self.customer_id, "customer_id")
        _require_text(self.registration_number, "registration_number")
        _require_text(self.make, "make")
        _require_text(self.model, "model")
        _optional_text(self.vin, "vin")
        if self.year is not None and (
            isinstance(self.year, bool) or not isinstance(self.year, int) or self.year < 1900
        ):
            raise ValueError("year must be a plausible model year.")


@dataclass(frozen=True)
class CustomerProfile:
    customer_id: str
    name: str
    phone_number: str  # normalised, see app.domain.phone_number
    email: str | None = None
    preferred_channel: MessagingChannel = MessagingChannel.SMS
    consent_status: ConsentStatus = ConsentStatus.UNKNOWN
    language: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.customer_id, "customer_id")
        _require_text(self.name, "name")
        _require_text(self.phone_number, "phone_number")
        _optional_text(self.email, "email")
        _optional_text(self.language, "language")
        if not isinstance(self.preferred_channel, MessagingChannel):
            raise TypeError("preferred_channel must be a MessagingChannel.")
        if not isinstance(self.consent_status, ConsentStatus):
            raise TypeError("consent_status must be a ConsentStatus.")

    def to_contact(self) -> CustomerContact:
        """The messaging view of this customer, used for summary delivery."""
        return CustomerContact(
            customer_id=self.customer_id,
            phone_number=self.phone_number,
            preferred_channel=self.preferred_channel,
            consent_status=self.consent_status,
            language=self.language,
        )
