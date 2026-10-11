from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.database.models import ReportLayoutModel
from app.infrastructure.database.repositories._saving import save_row
from app.services.report_layout import (
    ReportLayoutRepository,
    SavedLayout,
    layout_from_stored,
    layout_to_stored,
)

_KEY = "complaint_report"


class PostgresReportLayoutRepository(ReportLayoutRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self) -> SavedLayout | None:
        with self._session_factory() as session:
            model = session.get(ReportLayoutModel, _KEY)
            if model is None:
                return None
            return SavedLayout(
                layout_from_stored(model.layout), model.updated_at, model.updated_by
            )

    def save(self, saved: SavedLayout) -> None:
        save_row(
            self._session_factory,
            ReportLayoutModel(
                key=_KEY,
                layout=layout_to_stored(saved.layout),
                updated_at=saved.updated_at,
                updated_by=saved.updated_by,
            ),
        )
