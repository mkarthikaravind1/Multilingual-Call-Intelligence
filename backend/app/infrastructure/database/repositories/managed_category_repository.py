from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.managed_category import ManagedCategory, ManagedCategoryRepository
from app.infrastructure.database.models import ManagedCategoryModel
from app.infrastructure.database.repositories._saving import save_row


def _to_domain(model: ManagedCategoryModel) -> ManagedCategory:
    return ManagedCategory(
        key=model.key,
        name=model.name,
        description=model.description,
        former_names=tuple(model.former_names or ()),
        retired_at=model.retired_at,
        updated_at=model.updated_at,
        updated_by=model.updated_by,
    )


class PostgresManagedCategoryRepository(ManagedCategoryRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, category: ManagedCategory) -> None:
        save_row(
            self._session_factory,
            ManagedCategoryModel(
                key=category.key,
                name=category.name,
                description=category.description,
                former_names=list(category.former_names),
                retired_at=category.retired_at,
                updated_at=category.updated_at,
                updated_by=category.updated_by,
            ),
        )

    def get(self, key: str) -> ManagedCategory | None:
        with self._session_factory() as session:
            model = session.get(ManagedCategoryModel, key)
            return None if model is None else _to_domain(model)

    def list_all(self) -> tuple[ManagedCategory, ...]:
        with self._session_factory() as session:
            models = session.scalars(
                select(ManagedCategoryModel).order_by(ManagedCategoryModel.key)
            ).all()
            return tuple(_to_domain(model) for model in models)
