from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.conversation import ConversationStatus
from app.infrastructure.database.models import (
    ConversationModel,
    DatabaseBackupModel,
    TranscriptArchiveModel,
)
from app.infrastructure.database.repositories._saving import save_row
from app.services.database_backup import BackupRepository, BackupStatus, DatabaseBackup
from app.services.offsite_archive import (
    ArchivedTranscript,
    TranscriptArchiveRepository,
    TranscriptCounts,
)

_COMPLETED = ConversationStatus.COMPLETED.value


def _waiting(ended_before: float):
    """Completed calls that ended before ended_before and have no copy."""
    call, copy = ConversationModel, TranscriptArchiveModel
    return (
        select(call.call_id)
        .outerjoin(copy, copy.call_id == call.call_id)
        .where(call.status == _COMPLETED)
        .where(call.end_time.is_not(None))
        .where(call.end_time < ended_before)
        .where(copy.call_id.is_(None))
    )


class PostgresTranscriptArchiveRepository(TranscriptArchiveRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, call_id: str) -> ArchivedTranscript | None:
        with self._session_factory() as session:
            model = session.get(TranscriptArchiveModel, call_id)
            if model is None:
                return None
            return ArchivedTranscript(
                model.call_id, model.archive_key, model.sha256, model.size_bytes, model.archived_at
            )

    def save(self, transcript: ArchivedTranscript) -> None:
        save_row(
            self._session_factory,
            TranscriptArchiveModel(
                call_id=transcript.call_id,
                archive_key=transcript.archive_key,
                sha256=transcript.sha256,
                size_bytes=transcript.size_bytes,
                archived_at=transcript.archived_at,
            ),
        )

    def pending_call_ids(self, ended_before: float, limit: int) -> tuple[str, ...]:
        with self._session_factory() as session:
            return tuple(
                session.scalars(
                    _waiting(ended_before)
                    .order_by(ConversationModel.end_time, ConversationModel.call_id)
                    .limit(limit)
                ).all()
            )

    def counts(self, ended_before: float) -> TranscriptCounts:
        with self._session_factory() as session:
            archived = session.scalar(select(func.count()).select_from(TranscriptArchiveModel))
            pending = session.scalar(
                select(func.count()).select_from(_waiting(ended_before).subquery())
            )
            return TranscriptCounts(int(archived or 0), int(pending or 0))


def _backup(model: DatabaseBackupModel) -> DatabaseBackup:
    return DatabaseBackup(
        started_at=model.started_at,
        status=BackupStatus(model.status),
        finished_at=model.finished_at,
        archive_key=model.archive_key,
        size_bytes=model.size_bytes,
        sha256=model.sha256,
        error=model.error,
        removed_at=model.removed_at,
        backup_id=model.id,
    )


def _backup_model(backup: DatabaseBackup) -> DatabaseBackupModel:
    return DatabaseBackupModel(
        id=backup.backup_id,
        started_at=backup.started_at,
        status=backup.status.value,
        finished_at=backup.finished_at,
        archive_key=backup.archive_key,
        size_bytes=backup.size_bytes,
        sha256=backup.sha256,
        error=backup.error,
        removed_at=backup.removed_at,
    )


class PostgresBackupRepository(BackupRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, backup: DatabaseBackup) -> DatabaseBackup:
        with self._session_factory() as session, session.begin():
            model = _backup_model(backup)
            session.add(model)
            session.flush()
            return _backup(model)

    def save(self, backup: DatabaseBackup) -> None:
        save_row(self._session_factory, _backup_model(backup))

    def _newest_first(self):
        return select(DatabaseBackupModel).order_by(
            DatabaseBackupModel.started_at.desc(), DatabaseBackupModel.id.desc()
        )

    def list_recent(self, limit: int) -> tuple[DatabaseBackup, ...]:
        with self._session_factory() as session:
            return tuple(
                _backup(m) for m in session.scalars(self._newest_first().limit(limit)).all()
            )

    def latest_done(self) -> DatabaseBackup | None:
        with self._session_factory() as session:
            model = session.scalars(
                self._newest_first()
                .where(DatabaseBackupModel.status == BackupStatus.DONE.value)
                .limit(1)
            ).first()
            return None if model is None else _backup(model)

    def list_expired(self, started_before: float) -> tuple[DatabaseBackup, ...]:
        with self._session_factory() as session:
            models = session.scalars(
                self._newest_first()
                .where(DatabaseBackupModel.status == BackupStatus.DONE.value)
                .where(DatabaseBackupModel.removed_at.is_(None))
                .where(DatabaseBackupModel.started_at < started_before)
            ).all()
            return tuple(_backup(m) for m in models)
