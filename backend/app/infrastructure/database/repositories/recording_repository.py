from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.database.models import CallRecordingModel, RecordingPlayModel
from app.infrastructure.database.repositories._saving import save_row
from app.services.recording_archive import (
    RecordingPlay,
    RecordingRepository,
    StoredRecording,
)


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
            ),
        )

    def get(self, call_id: str) -> StoredRecording | None:
        with self._session_factory() as session:
            model = session.get(CallRecordingModel, call_id)
            return None if model is None else _to_domain(model)

    def list_expired(self, now: float) -> tuple[StoredRecording, ...]:
        with self._session_factory() as session:
            models = session.scalars(
                select(CallRecordingModel)
                .where(CallRecordingModel.deleted_at.is_(None))
                .where(CallRecordingModel.delete_after <= now)
                .order_by(CallRecordingModel.delete_after)
            ).all()
            return tuple(_to_domain(model) for model in models)

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
