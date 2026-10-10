"""Which location and executive a phone call belongs to, and who to ring.

An incoming call belongs to the location whose number was dialled, and
rings that location's executives; the one who answers is the call's
executive. A call an executive places from their own dial target is an
outgoing call: theirs, at their location, to the number they dialled.
"""

import logging
from dataclasses import dataclass

from app.domain.conversation import CallDirection
from app.domain.location import Location, LocationRepository
from app.domain.phone_number import normalize_dial_target
from app.domain.user import User
from app.domain.user_repository import UserRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallRoute:
    direction: CallDirection = CallDirection.INBOUND
    location_id: str | None = None
    # Known from the start only for an outgoing call.
    executive_user_id: str | None = None
    # The customer's number: the caller of an incoming call, the number
    # dialled on an outgoing one.
    customer_number: str = ""
    # Who the provider is to ring; empty: whoever it is configured to ring.
    dial_targets: tuple[str, ...] = ()
    # The number shown to whoever is rung; None: as configured.
    caller_id: str | None = None


class CallRoutingService:
    def __init__(
        self,
        locations: LocationRepository,
        users: UserRepository,
        default_country_code: str = "",
    ) -> None:
        self._locations = locations
        self._users = users
        self._default_country_code = default_country_code

    def route(self, from_number: str, to_number: str) -> CallRoute:
        """The route of a phone call from from_number to to_number."""
        dialled = self._normalize(to_number)
        location = self._location_for_number(dialled)
        caller = self.executive_for_target(from_number)
        if caller is not None and location is None and dialled is not None:
            own_location = self._active_location(caller.location_id)
            return CallRoute(
                direction=CallDirection.OUTBOUND,
                location_id=caller.location_id,
                executive_user_id=caller.user_id,
                customer_number=to_number,
                dial_targets=(dialled,),
                caller_id=None if own_location is None else own_location.phone_number,
            )

        if location is None:
            if self._locations.list_all():
                logger.warning("A call came in on %r, which is no location's number", to_number)
            return CallRoute(customer_number=from_number)
        return CallRoute(
            location_id=location.location_id,
            customer_number=from_number,
            dial_targets=tuple(
                user.dial_target
                for user in self._users.list_all()
                if user.is_active and user.dial_target and user.location_id == location.location_id
            ),
        )

    def executive_for_target(self, dial_target: str | None) -> User | None:
        """The active user reached at (or calling from) this dial target."""
        target = self._normalize(dial_target)
        if target is None:
            return None
        for user in self._users.list_all():
            if user.is_active and user.dial_target == target:
                return user
        return None

    def _normalize(self, raw: str | None) -> str | None:
        return normalize_dial_target(raw, self._default_country_code)

    def _location_for_number(self, number: str | None) -> Location | None:
        if number is None:
            return None
        for location in self._locations.list_all():
            if location.is_active and location.phone_number == number:
                return location
        return None

    def _active_location(self, location_id: str | None) -> Location | None:
        if location_id is None:
            return None
        location = self._locations.get(location_id)
        return location if location is not None and location.is_active else None
