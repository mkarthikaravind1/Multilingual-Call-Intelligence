from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.database.models import CallRecordingModel, RecordingPlayModel
from app.infrastructure.database.repositories._saving import save_row
from app.services.recording_archive import (
    RecordingCounts,
    RecordingIntegrity,
    RecordingPlay,
    RecordingRepository,
    StoredRecording,
)

_KEPT = CallRecordingModel.deleted_at.is_(None)
_LOST = RecordingIntegrity.LOST.value


def _to_domain(model: CallRecordingModel) -> StoredRecording:
    return StoredRecording(
        call_id=model.call_id,
        file_name=model.file_name,
        duration_seconds=model.duration_seconds,
        size_bytes=model.size_bytes,
        sample_rate=model.sample_rate,
        channels=model.channels,
        created_at=model.created_at,
        delete_after=model.delete_after,
        deleted_at=model.deleted_at,
        sha256=model.sha256,
        archive_key=model.archive_key,
        archived_at=model.archived_at,
        verified_at=model.verified_at,
        integrity=None if model.integrity is None else RecordingIntegrity(model.integrity),
    )


class PostgresRecordingRepository(RecordingRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, recording: StoredRecording) -> None:
        save_row(
            self._session_factory,
            CallRecordingModel(
                call_id=recording.call_id,
                file_name=recording.file_name,
                duration_seconds=recording.duration_seconds,
                size_bytes=recording.size_bytes,
                sample_rate=recording.sample_rate,
                channels=recording.channels,
                created_at=recording.created_at,
                delete_after=recording.delete_after,
                deleted_at=recording.deleted_at,
                sha256=recording.sha256,
                archive_key=recording.archive_key,
                archived_at=recording.archived_at,
                verified_at=recording.verified_at,
                integrity=None if recording.integrity is None else recording.integrity.value,
            ),
        )

    def get(self, call_id: str) -> StoredRecording | None:
        with self._session_factory() as session:
            model = session.get(CallRecordingModel, call_id)
            return None if model is None else _to_domain(model)

    def _list(self, query) -> tuple[StoredRecording, ...]:
        with self._session_factory() as session:
            return tuple(_to_domain(model) for model in session.scalars(query).all())

    def list_expired(self, now: float) -> tuple[StoredRecording, ...]:
        return self._list(
            select(CallRecordingModel)
            .where(_KEPT)
            .where(CallRecordingModel.delete_after <= now)
            .order_by(CallRecordingModel.delete_after)
        )

    def add_play(self, play: RecordingPlay) -> None:
        with self._session_factory() as session, session.begin():
            session.add(
                RecordingPlayModel(
                    call_id=play.call_id, user_id=play.user_id, played_at=play.played_at
                )
            )

    def list_plays(self, call_id: str) -> tuple[RecordingPlay, ...]:
        with self._session_factory() as session:
            models = session.scalars(
                select(RecordingPlayModel)
                .where(RecordingPlayModel.call_id == call_id)
                .order_by(RecordingPlayModel.played_at, RecordingPlayModel.id)
            ).all()
            return tuple(RecordingPlay(m.call_id, m.user_id, m.played_at) for m in models)

    def list_unarchived(self, limit: int) -> tuple[StoredRecording, ...]:
        return self._list(
            select(CallRecordingModel)
            .where(_KEPT)
            .where(CallRecordingModel.archived_at.is_(None))
            .order_by(CallRecordingModel.created_at)
            .limit(limit)
        )

    def list_to_verify(
        self, limit: int, verified_before: float | None = None
    ) -> tuple[StoredRecording, ...]:
        query = select(CallRecordingModel).where(_KEPT)
        if verified_before is not None:
            query = query.where(
                or_(
                    CallRecordingModel.verified_at.is_(None),
                    CallRecordingModel.verified_at < verified_before,
                )
            )
        return self._list(
            query.order_by(
                CallRecordingModel.verified_at.is_not(None), CallRecordingModel.verified_at
            )
            .limit(limit)
        )

    def list_removed_with_copy(self, limit: int) -> tuple[StoredRecording, ...]:
        return self._list(
            select(CallRecordingModel)
            .where(CallRecordingModel.deleted_at.is_not(None))
            .where(CallRecordingModel.archive_key.is_not(None))
            .limit(limit)
        )

    def list_lost(self, limit: int) -> tuple[StoredRecording, ...]:
        return self._list(
            select(CallRecordingModel)
            .where(_KEPT)
            .where(CallRecordingModel.integrity == _LOST)
            .order_by(CallRecordingModel.created_at.desc())
            .limit(limit)
        )

    def counts(self) -> RecordingCounts:
        model = CallRecordingModel
        with self._session_factory() as session:
            kept, archived, checked, lost = session.execute(
                select(
                    func.count(),
                    func.count(model.archived_at),
                    func.count(model.verified_at),
                    func.count().filter(model.integrity == _LOST),
                )
                .select_from(model)
                .where(_KEPT)
            ).one()
            return RecordingCounts(int(kept), int(archived), int(checked), int(lost))
