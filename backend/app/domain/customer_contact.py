from dataclasses import dataclass
from enum import Enum


class MessagingChannel(str, Enum):
    SMS = "sms"
    WHATSAPP = "whatsapp"


class ConsentStatus(str, Enum):
    GRANTED = "granted"
    REVOKED = "revoked"
    UNKNOWN = "unknown"


def _require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


@dataclass(frozen=True)
class CustomerContact:
    customer_id: str
    phone_number: str
    preferred_channel: MessagingChannel = MessagingChannel.SMS
    consent_status: ConsentStatus = ConsentStatus.UNKNOWN
    language: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.customer_id, "customer_id")
        _require_non_empty(self.phone_number, "phone_number")

        if not isinstance(self.preferred_channel, MessagingChannel):
            raise TypeError(
                "preferred_channel must be a MessagingChannel, "
                f"got {type(self.preferred_channel).__name__}."
            )

        if not isinstance(self.consent_status, ConsentStatus):
            raise TypeError(
                "consent_status must be a ConsentStatus, "
                f"got {type(self.consent_status).__name__}."
            )

        if self.language is not None:
            _require_non_empty(self.language, "language")

    @property
    def normalized_phone_number(self) -> str:
        return self.phone_number.strip()

    def can_receive_summary(self, channel: MessagingChannel | None = None) -> bool:
        target_channel = self.preferred_channel if channel is None else channel
        return self.consent_status == ConsentStatus.GRANTED and target_channel in {
            self.preferred_channel,
            MessagingChannel.SMS,
            MessagingChannel.WHATSAPP,
        }
