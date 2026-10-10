import dataclasses
import logging
import threading
import time
from uuid import uuid4

from app.domain.location import Location, LocationRepository
from app.domain.phone_number import normalize_phone_number
from app.domain.user_repository import UserRepository

logger = logging.getLogger(__name__)

MAX_NAME_LENGTH = 100


class LocationNotFoundError(Exception):
    def __init__(self, location_id: str) -> None:
        super().__init__(f"No location {location_id!r}.")
        self.location_id = location_id


class LocationError(ValueError):
    """A location that would clash with another one, or an invalid value."""


class LocationService:
    """The service centres customers call. A location is never deleted, so
    the calls it took keep it; one that closes is deactivated."""

    def __init__(
        self,
        repository: LocationRepository,
        users: UserRepository | None = None,
        default_country_code: str = "",
    ) -> None:
        self._repository = repository
        self._users = users
        self._default_country_code = default_country_code
        self._lock = threading.Lock()

    def list_locations(self) -> tuple[Location, ...]:
        return self._repository.list_all()

    def get(self, location_id: str) -> Location:
        location = self._repository.get(location_id)
        if location is None:
            raise LocationNotFoundError(location_id)
        return location

    def create_location(self, name: str, phone_number: str) -> Location:
        with self._lock:
            location = Location(
                location_id=str(uuid4()),
                name=self._free_name(name, None),
                phone_number=self._free_number(phone_number, None),
                is_active=True,
                created_at=time.time(),
            )
            self._repository.save(location)
        logger.info("Created location %s", location.name)
        return location

    def update_location(
        self,
        location_id: str,
        name: str | None = None,
        phone_number: str | None = None,
        is_active: bool | None = None,
    ) -> Location:
        with self._lock:
            location = self.get(location_id)
            updated = dataclasses.replace(
                location,
                name=location.name if name is None else self._free_name(name, location_id),
                phone_number=(
                    location.phone_number
                    if phone_number is None
                    else self._free_number(phone_number, location_id)
                ),
                is_active=location.is_active if is_active is None else is_active,
            )
            self._repository.save(updated)
        logger.info("Updated location %s (active=%s)", updated.name, updated.is_active)
        return updated

    def _free_name(self, name: str, own_id: str | None) -> str:
        name = " ".join(name.split())
        if not name:
            raise LocationError("A location needs a name.")
        if len(name) > MAX_NAME_LENGTH:
            raise LocationError(f"A location name can be at most {MAX_NAME_LENGTH} characters.")
        for other in self._repository.list_all():
            if other.location_id != own_id and other.name.casefold() == name.casefold():
                raise LocationError(f"There is already a location called {other.name!r}.")
        return name

    def _free_number(self, phone_number: str, own_id: str | None) -> str:
        number = normalize_phone_number(phone_number, self._default_country_code)
        if number is None:
            raise LocationError("Enter the number customers dial, with its country code.")
        for other in self._repository.list_all():
            if other.location_id != own_id and other.phone_number == number:
                raise LocationError(f"{number} is already the number of {other.name!r}.")
        # A call to this number would be sent on to itself.
        if self._users is not None and any(
            user.dial_target == number for user in self._users.list_all()
        ):
            raise LocationError(f"{number} is already a user's own number.")
        return number
