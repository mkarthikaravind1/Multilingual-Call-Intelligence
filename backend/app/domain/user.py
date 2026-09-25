from dataclasses import dataclass
from enum import Enum


class UserRole(str, Enum):
    ICR = "ICR"
    SUPERVISOR = "SUPERVISOR"
    ADMIN = "ADMIN"


@dataclass(frozen=True)
class User:
    user_id: str
    email: str
    password_hash: str
    role: UserRole
    is_active: bool
    created_at: float

    def __post_init__(self) -> None:
        if not self.user_id.strip():
            raise ValueError("user_id must not be empty.")

        if not self.email.strip() or "@" not in self.email:
            raise ValueError("email must be a valid, non-empty address.")

        if not self.password_hash.strip():
            raise ValueError("password_hash must not be empty.")

        if not isinstance(self.role, UserRole):
            raise TypeError(f"role must be a UserRole, got {type(self.role).__name__}.")

        if not isinstance(self.is_active, bool):
            raise TypeError(f"is_active must be a bool, got {type(self.is_active).__name__}.")

        if isinstance(self.created_at, bool) or not isinstance(self.created_at, (int, float)):
            raise TypeError(f"created_at must be a number, got {type(self.created_at).__name__}.")
        if self.created_at < 0:
            raise ValueError("created_at must not be negative.")