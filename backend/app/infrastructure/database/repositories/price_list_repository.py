from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.estimation.price_list import (
    PriceListRow,
    PriceListSettings,
    row_from_json,
    row_to_json,
    settings_from_json,
    settings_to_json,
)
from app.infrastructure.database.models import PriceListVersionModel
from app.services.price_list_repository import (
    KEPT_VERSIONS,
    PriceListRepository,
    PriceListVersion,
    PriceListVersionInfo,
)


def _info(model: PriceListVersionModel, active_id: int | None) -> PriceListVersionInfo:
    return PriceListVersionInfo(
        version_id=model.version_id,
        created_at=model.created_at,
        created_by=model.created_by,
        source=model.source,
        note=model.note,
        row_count=model.row_count,
        is_active=model.version_id == active_id,
    )


def _to_domain(model: PriceListVersionModel, active_id: int | None) -> PriceListVersion:
    return PriceListVersion(
        _info(model, active_id),
        settings_from_json(model.settings),
        tuple(row_from_json(row) for row in model.rows),
    )


class PostgresPriceListRepository(PriceListRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_active(self) -> PriceListVersion | None:
        with self._session_factory() as session:
            model = session.scalars(
                select(PriceListVersionModel)
                .order_by(PriceListVersionModel.version_id.desc())
                .limit(1)
            ).first()
            return None if model is None else _to_domain(model, model.version_id)

    def get(self, version_id: int) -> PriceListVersion | None:
        with self._session_factory() as session:
            model = session.get(PriceListVersionModel, version_id)
            if model is None:
                return None
            return _to_domain(model, self._active_id(session))

    def add(
        self,
        settings: PriceListSettings,
        rows: tuple[PriceListRow, ...],
        *,
        created_at: float,
        created_by: str | None,
        source: str,
        note: str | None = None,
    ) -> PriceListVersion:
        with self._session_factory() as session, session.begin():
            model = PriceListVersionModel(
                created_at=created_at,
                created_by=created_by,
                source=source,
                note=note,
                row_count=len(rows),
                settings=settings_to_json(settings),
                rows=[row_to_json(row) for row in rows],
            )
            session.add(model)
            session.flush()
            kept = (
                select(PriceListVersionModel.version_id)
                .order_by(PriceListVersionModel.version_id.desc())
                .limit(KEPT_VERSIONS)
                .scalar_subquery()
            )
            session.execute(
                delete(PriceListVersionModel).where(
                    PriceListVersionModel.version_id.not_in(kept)
                )
            )
            return _to_domain(model, model.version_id)

    def list_versions(self, limit: int = KEPT_VERSIONS) -> tuple[PriceListVersionInfo, ...]:
        with self._session_factory() as session:
            # Without the rows column: only the summaries are needed.
            models = session.execute(
                select(
                    PriceListVersionModel.version_id,
                    PriceListVersionModel.created_at,
                    PriceListVersionModel.created_by,
                    PriceListVersionModel.source,
                    PriceListVersionModel.note,
                    PriceListVersionModel.row_count,
                )
                .order_by(PriceListVersionModel.version_id.desc())
                .limit(limit)
            ).all()
            active_id = models[0].version_id if models else None
            return tuple(
                PriceListVersionInfo(
                    version_id=m.version_id,
                    created_at=m.created_at,
                    created_by=m.created_by,
                    source=m.source,
                    note=m.note,
                    row_count=m.row_count,
                    is_active=m.version_id == active_id,
                )
                for m in models
            )

    @staticmethod
    def _active_id(session: Session) -> int | None:
        return session.scalar(select(func.max(PriceListVersionModel.version_id)))
