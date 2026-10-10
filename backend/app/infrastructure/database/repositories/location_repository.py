from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.location import Location, LocationRepository
from app.infrastructure.database.models import LocationModel
from app.infrastructure.database.repositories._saving import save_row


def _to_domain(model: LocationModel) -> Location:
    return Location(
        location_id=model.location_id,
        name=model.name,
        phone_number=model.phone_number,
        is_active=model.is_active,
        created_at=model.created_at,
    )


class PostgresLocationRepository(LocationRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, location: Location) -> None:
        save_row(
            self._session_factory,
            LocationModel(
                location_id=location.location_id,
                name=location.name,
                phone_number=location.phone_number,
                is_active=location.is_active,
                created_at=location.created_at,
            ),
        )

    def get(self, location_id: str) -> Location | None:
        with self._session_factory() as session:
            model = session.get(LocationModel, location_id)
            return None if model is None else _to_domain(model)

    def list_all(self) -> tuple[Location, ...]:
        with self._session_factory() as session:
            models = session.scalars(
                select(LocationModel).order_by(func.lower(LocationModel.name))
            ).all()
            return tuple(_to_domain(model) for model in models)
