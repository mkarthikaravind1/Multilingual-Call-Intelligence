import dataclasses
import logging
import threading
import time

from app.domain.user import User, UserRole
from app.domain.user_repository import UserRepository
from app.security.password import MAX_PASSWORD_BYTES, hash_password, password_too_long
from app.services.auth_service import AuthService, EmailAlreadyRegisteredError

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 8


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

    def __init__(self, repository: UserRepository, auth_service: AuthService) -> None:
        self._repository = repository
        self._auth = auth_service
        self._lock = threading.Lock()

    def list_users(self) -> tuple[User, ...]:
        return self._repository.list_all()

    def create_user(self, email: str, password: str, role: UserRole) -> User:
        _check_password(password)
        with self._lock:
            email = normalize_email(email)
            if self._repository.get_by_email(email) is not None:
                raise EmailAlreadyRegisteredError(f"Email already registered: {email!r}.")
            user = self._auth.register(email, password, role)
        logger.info("Created %s user %s", role.value, email)
        return user

    def update_user(
        self,
        user_id: str,
        acting_user: User,
        role: UserRole | None = None,
        is_active: bool | None = None,
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

            updated = dataclasses.replace(user, role=new_role, is_active=new_active)
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

    def _active_admin_count(self) -> int:
        return sum(
            1 for u in self._repository.list_all() if u.role is UserRole.ADMIN and u.is_active
        )


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
