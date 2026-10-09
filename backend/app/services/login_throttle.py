"""Limits password guessing: after too many failed sign-ins for an email,
or from one address, sign-in is refused for a while. Counts are kept in the
live state store (Redis when several instances run), so every instance
enforces the same limit."""

import hashlib
import logging
from dataclasses import dataclass

from app.services.live_state_store import LiveStateStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoginLimits:
    max_failures_per_email: int = 5
    max_failures_per_address: int = 20
    # Failures count for this long from the first one; a locked email or
    # address can try again when it has passed.
    window_seconds: float = 900.0


class LoginThrottle:
    def __init__(self, store: LiveStateStore, limits: LoginLimits = LoginLimits()) -> None:
        self._store = store
        self._limits = limits

    def locked(self, email: str, address: str | None) -> bool:
        """Whether sign-in is refused now. If the store cannot be read,
        sign-in is allowed (and logged): an outage must not lock everyone out."""
        try:
            if self._count(_email_key(email)) >= self._limits.max_failures_per_email:
                return True
            return (
                address is not None
                and self._count(_address_key(address)) >= self._limits.max_failures_per_address
            )
        except Exception:
            logger.exception("Could not read sign-in failure counts; allowing the attempt")
            return False

    def failed(self, email: str, address: str | None) -> None:
        try:
            self._store.increment(_email_key(email), self._limits.window_seconds)
            if address is not None:
                self._store.increment(_address_key(address), self._limits.window_seconds)
        except Exception:
            logger.exception("Could not record a failed sign-in")

    def succeeded(self, email: str) -> None:
        """A correct password clears the email's failures (not the address's,
        so one known account cannot be used to keep guessing others)."""
        try:
            self._store.delete(_email_key(email))
        except Exception:
            logger.exception("Could not clear sign-in failures")

    @property
    def window_seconds(self) -> float:
        return self._limits.window_seconds

    def _count(self, key: str) -> int:
        return int(self._store.get_json(key) or 0)


def _email_key(email: str) -> str:
    # Hashed: the store never holds the address itself.
    digest = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
    return f"login_failures:email:{digest}"


def _address_key(address: str) -> str:
    return f"login_failures:address:{address}"
