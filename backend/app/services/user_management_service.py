import dataclasses
import logging
import threading
import time

from app.domain.location import LocationRepository
from app.domain.phone_number import normalize_dial_target
from app.domain.user import User, UserRole
from app.domain.user_repository import UserRepository
from app.security.password import MAX_PASSWORD_BYTES, hash_password, password_too_long
from app.services.auth_service import AuthService, EmailAlreadyRegisteredError

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 8
MAX_DISPLAY_NAME_LENGTH = 100


class _Unchanged:
    """Marks a value update_user() is to leave as it is (None clears it)."""


UNCHANGED = _Unchanged()


class UserNotFoundError(Exception):
    def __init__(self, user_id: str) -> None:
        super().__init__(f"No user {user_id!r}.")
        self.user_id = user_id


class UserManagementError(ValueError):
    """A change that would leave the system without a way to administer it,
    or an invalid value."""


def normalize_email(email: str) -> str:
    return email.strip().lower()


class UserManagementService:
    """Admin-side user provisioning: create users, change roles, deactivate
    and reactivate, and reset passwords. Deactivation takes effect on the
    user's next request, because every request re-reads the user.

    It never lets the last active admin be demoted or deactivated, and an
    admin cannot deactivate or demote themselves."""

    def __init__(
        self,
        repository: UserRepository,
        auth_service: AuthService,
        locations: LocationRepository | None = None,
        default_country_code: str = "",
    ) -> None:
        self._repository = repository
        self._auth = auth_service
        self._locations = locations
        self._default_country_code = default_country_code
        self._lock = threading.Lock()

    def list_users(self) -> tuple[User, ...]:
        return self._repository.list_all()

    def create_user(
        self,
        email: str,
        password: str,
        role: UserRole,
        display_name: str | None = None,
        location_id: str | None = None,
        dial_target: str | None = None,
    ) -> User:
        _check_password(password)
        with self._lock:
            email = normalize_email(email)
            if self._repository.get_by_email(email) is not None:
                raise EmailAlreadyRegisteredError(f"Email already registered: {email!r}.")
            # Checked before the user exists, so a bad value leaves no user behind.
            display_name = _display_name(display_name)
            location_id = self._location_id(location_id)
            dial_target = self._free_dial_target(dial_target, None)
            user = self._auth.register(email, password, role)
            if display_name or location_id or dial_target:
                user = dataclasses.replace(
                    user,
                    display_name=display_name,
                    location_id=location_id,
                    dial_target=dial_target,
                )
                self._repository.save(user)
        logger.info("Created %s user %s", role.value, email)
        return user

    def update_user(
        self,
        user_id: str,
        acting_user: User,
        role: UserRole | None = None,
        is_active: bool | None = None,
        display_name: str | None | _Unchanged = UNCHANGED,
        location_id: str | None | _Unchanged = UNCHANGED,
        dial_target: str | None | _Unchanged = UNCHANGED,
    ) -> User:
        with self._lock:
            user = self._require(user_id)
            new_role = user.role if role is None else role
            new_active = user.is_active if is_active is None else is_active

            if user.user_id == acting_user.user_id and (
                not new_active or new_role is not UserRole.ADMIN
            ):
                raise UserManagementError(
                    "You cannot deactivate your own account or remove your own admin role."
                )
            loses_admin = (
                user.role is UserRole.ADMIN
                and user.is_active
                and (new_role is not UserRole.ADMIN or not new_active)
            )
            if loses_admin and self._active_admin_count() <= 1:
                raise UserManagementError("At least one active admin must remain.")

            updated = dataclasses.replace(
                user,
                role=new_role,
                is_active=new_active,
                display_name=(
                    user.display_name
                    if isinstance(display_name, _Unchanged)
                    else _display_name(display_name)
                ),
                location_id=(
                    user.location_id
                    if isinstance(location_id, _Unchanged)
                    else self._location_id(location_id)
                ),
                dial_target=(
                    user.dial_target
                    if isinstance(dial_target, _Unchanged)
                    else self._free_dial_target(dial_target, user.user_id)
                ),
            )
            self._repository.save(updated)
        logger.info(
            "%s updated user %s: role=%s active=%s",
            acting_user.email,
            user.email,
            new_role.value,
            new_active,
        )
        return updated

    def reset_password(self, user_id: str, new_password: str, acting_user: User) -> User:
        _check_password(new_password)
        with self._lock:
            user = self._require(user_id)
            updated = dataclasses.replace(
                user,
                password_hash=hash_password(new_password),
                # Signs the user out everywhere: older sessions stop working.
                password_changed_at=time.time(),
            )
            self._repository.save(updated)
        logger.info("%s reset the password of %s", acting_user.email, user.email)
        return updated

    def bootstrap_admin(self, email: str, password: str) -> User | None:
        """Create the first admin when there are no users at all, so a fresh
        deployment can be signed into. Does nothing once any user exists."""
        if not email.strip() or not password:
            return None
        if self._repository.list_all():
            return None
        user = self.create_user(email, password, UserRole.ADMIN)
        logger.warning("Bootstrapped the first admin user %s; change its password", user.email)
        return user

    def _require(self, user_id: str) -> User:
        user = self._repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(user_id)
        return user

    def _location_id(self, location_id: str | None) -> str | None:
        if not location_id:
            return None
        if self._locations is None or self._locations.get(location_id) is None:
            raise UserManagementError("That location does not exist.")
        return location_id

    def _free_dial_target(self, dial_target: str | None, own_id: str | None) -> str | None:
        """The dial target in its stored form, once no other user and no
        location has it: the answering executive is known by it."""
        if dial_target is None or not dial_target.strip():
            return None
        target = normalize_dial_target(dial_target, self._default_country_code)
        if target is None:
            raise UserManagementError(
                "Enter a phone number with its country code, or a SIP address (sip:name@host)."
            )
        for other in self._repository.list_all():
            if other.user_id != own_id and other.dial_target == target:
                raise UserManagementError(f"{target} is already the dial target of {other.email}.")
        if self._locations is not None and any(
            location.phone_number == target for location in self._locations.list_all()
        ):
            # A call to that location would be sent on to itself.
            raise UserManagementError(f"{target} is the number customers dial for a location.")
        return target

    def _active_admin_count(self) -> int:
        return sum(
            1 for u in self._repository.list_all() if u.role is UserRole.ADMIN and u.is_active
        )


def _display_name(display_name: str | None) -> str | None:
    name = " ".join((display_name or "").split())
    if len(name) > MAX_DISPLAY_NAME_LENGTH:
        raise UserManagementError(
            f"A name can be at most {MAX_DISPLAY_NAME_LENGTH} characters long."
        )
    return name or None


def _check_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise UserManagementError(
            f"Passwords must be at least {MIN_PASSWORD_LENGTH} characters long."
        )
    if password_too_long(password):
        raise UserManagementError(
            f"Passwords must be at most {MAX_PASSWORD_BYTES} bytes long "
            f"(about {MAX_PASSWORD_BYTES} English letters, fewer in Indian scripts)."
        )
