from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    """A service centre customers call: its name and the number they dial."""

    location_id: str
    name: str
    # As "+<digits>" (see app.domain.phone_number).
    phone_number: str
    is_active: bool
    created_at: float

    def __post_init__(self) -> None:
        if not self.location_id.strip():
            raise ValueError("location_id must not be empty.")
        if not self.name.strip():
            raise ValueError("A location needs a name.")
        if not self.phone_number.strip():
            raise ValueError("A location needs the number customers dial.")


class LocationRepository(ABC):
    @abstractmethod
    def save(self, location: Location) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, location_id: str) -> Location | None:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> tuple[Location, ...]:
        """Every location, by name."""
        raise NotImplementedError


class InMemoryLocationRepository(LocationRepository):
    def __init__(self) -> None:
        self._by_id: dict[str, Location] = {}

    def save(self, location: Location) -> None:
        self._by_id[location.location_id] = location

    def get(self, location_id: str) -> Location | None:
        return self._by_id.get(location_id)

    def list_all(self) -> tuple[Location, ...]:
        return tuple(sorted(self._by_id.values(), key=lambda l: l.name.casefold()))
