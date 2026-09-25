from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.user import User, UserRole
from app.domain.user_repository import UserRepository
from app.infrastructure.database.models import UserModel


def _to_domain(model: UserModel) -> User:
    return User(
        user_id=model.user_id,
        email=model.email,
        password_hash=model.password_hash,
        role=UserRole(model.role),
        is_active=model.is_active,
        created_at=model.created_at,
    )


def _to_model(user: User) -> UserModel:
    return UserModel(
        user_id=user.user_id,
        email=user.email,
        password_hash=user.password_hash,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
    )


class PostgresUserRepository(UserRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, user: User) -> None:
        with self._session_factory() as session, session.begin():
            existing = session.get(UserModel, user.user_id)
            if existing is not None:
                session.delete(existing)
                session.flush()
            session.add(_to_model(user))

    def get_by_id(self, user_id: str) -> User | None:
        with self._session_factory() as session:
            model = session.get(UserModel, user_id)
            return None if model is None else _to_domain(model)

    def get_by_email(self, email: str) -> User | None:
        with self._session_factory() as session:
            model = session.scalar(select(UserModel).where(UserModel.email == email))
            return None if model is None else _to_domain(model)