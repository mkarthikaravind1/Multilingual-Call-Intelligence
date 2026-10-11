"""Builds what keeps the data safe beyond this server: the copies off the
server, the recording check and the database backups."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.core.config import Settings
from app.domain.conversation import Conversation
from app.domain.post_call_summary import PostCallSummary
from app.services.database_backup import (
    BackupRepository,
    DatabaseBackupService,
    pg_dump_command,
    pg_dump_to,
)
from app.services.live_state_store import LiveStateStore
from app.services.object_storage import ObjectStorage, build_object_storage
from app.services.offsite_archive import (
    OffsiteArchive,
    RecordingIntegrityChecker,
    TranscriptArchiveRepository,
)
from app.services.recording_archive import RecordingArchive, RecordingRepository, parse_key

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DataSafety:
    # Where copies go; None when nothing leaves the server.
    storage: ObjectStorage | None = None
    offsite: OffsiteArchive | None = None
    # None when this server keeps no recordings.
    integrity: RecordingIntegrityChecker | None = None
    backups: DatabaseBackupService | None = None


def build_data_safety(
    settings: Settings,
    live_state: LiveStateStore,
    recording_archive: RecordingArchive | None,
    recording_repository: RecordingRepository | None,
    transcripts: TranscriptArchiveRepository,
    backup_repository: BackupRepository,
    get_call: Callable[[str], Conversation],
    get_summary: Callable[[str], PostCallSummary | None],
) -> DataSafety:
    """What the settings ask for. A part that is asked for but cannot be
    built stops a production start (see production_checks too); elsewhere
    it is logged and left out."""
    storage = offsite = backups = None
    try:
        storage = build_object_storage(settings)
        if storage is not None:
            key = parse_key(settings.archive_encryption_key, "ARCHIVE_ENCRYPTION_KEY")
            offsite = OffsiteArchive(
                storage,
                key,
                transcripts,
                get_call,
                get_summary,
                live_state,
                recordings=recording_archive,
                recording_repository=recording_repository,
                transcript_delay_seconds=settings.archive_transcript_delay_seconds,
                batch_size=settings.archive_batch_size,
            )
            if settings.backup_enabled:
                _, _, database_name = pg_dump_command(settings.database_url)
                backups = DatabaseBackupService(
                    storage,
                    key,
                    backup_repository,
                    pg_dump_to(
                        settings.database_url,
                        settings.backup_pg_dump_path,
                        settings.backup_timeout_seconds,
                    ),
                    live_state,
                    interval_seconds=settings.backup_interval_seconds,
                    retention_days=settings.backup_retention_days,
                    database_name=database_name,
                )
        elif settings.backup_enabled:
            raise ValueError("BACKUP_ENABLED needs ARCHIVE_STORAGE_PROVIDER to say where backups go.")
    except Exception as exc:
        if settings.is_production:
            raise
        logger.error("Copies off the server and backups are NOT running: %s", exc)
        storage = offsite = backups = None

    integrity = None
    if recording_archive is not None and recording_repository is not None:
        integrity = RecordingIntegrityChecker(
            recording_archive,
            recording_repository,
            live_state,
            storage=storage,
            recheck_seconds=settings.integrity_check_interval_seconds,
            batch_size=settings.integrity_check_batch_size,
        )
    return DataSafety(storage=storage, offsite=offsite, integrity=integrity, backups=backups)
