import time
from uuid import uuid4

from app.domain.user import User, UserRole
from app.domain.user_repository import UserRepository
from app.security.password import hash_password, verify_password


class InvalidCredentialsError(Exception):
    pass


class EmailAlreadyRegisteredError(Exception):
    pass


class AuthService:
    def __init__(self, user_repository: UserRepository) -> None:
        self._user_repository = user_repository

    def register(self, email: str, password: str, role: UserRole) -> User:
        if self._user_repository.get_by_email(email) is not None:
            raise EmailAlreadyRegisteredError(f"Email already registered: {email!r}.")

        user = User(
            user_id=str(uuid4()),
            email=email,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
            created_at=time.time(),
        )
        self._user_repository.save(user)
        return user

    def authenticate(self, email: str, password: str) -> User:
        user = self._user_repository.get_by_email(email)
        # Same generic error whether the email is unknown or the password is
        # wrong, and whether the account is inactive — never reveal which.
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("Invalid email or password.")
        return user