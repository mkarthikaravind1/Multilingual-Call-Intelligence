"""Where the data stands beyond this server: copies off the server, the
recording check and the database backups. Administrators only."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict

from app.api.security_dependencies import require_roles
from app.composition.data_safety import DataSafety
from app.domain.user import User, UserRole
from app.services.database_backup import BackupStatus
from app.services.recording_archive import RecordingCounts

router = APIRouter(prefix="/admin/data-safety", tags=["administration"])

_ADMINS = require_roles(UserRole.ADMIN)
RECENT_BACKUPS = 10
LOST_SHOWN = 50


class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ArchiveRunResponse(_Response):
    ran_at: float
    recordings_copied: int
    transcripts_copied: int
    copies_removed: int
    failed: int
    last_error: str | None
    skipped_reason: str | None


class IntegrityRunResponse(_Response):
    ran_at: float
    checked: int
    ok: int
    repaired: int
    lost: int
    skipped_reason: str | None


class BackupResponse(_Response):
    backup_id: int | None
    started_at: float
    finished_at: float | None
    status: BackupStatus
    archive_key: str | None
    size_bytes: int | None
    error: str | None
    removed_at: float | None


class LostRecordingResponse(BaseModel):
    call_id: str
    created_at: float
    verified_at: float | None


class DataSafetyResponse(BaseModel):
    # Copies off the server.
    archive_enabled: bool
    # "S3 bucket calls-archive", "folder data/archive"; None when off.
    storage: str | None
    transcripts_archived: int
    transcripts_pending: int
    last_archive_run: ArchiveRunResponse | None
    # Recordings and their check.
    recordings_enabled: bool
    recordings_kept: int
    recordings_archived: int
    recordings_checked: int
    recordings_lost: int
    lost: list[LostRecordingResponse]
    last_integrity_run: IntegrityRunResponse | None
    # Database backups.
    backups_enabled: bool
    backup_interval_seconds: float | None
    backup_retention_days: float | None
    backups: list[BackupResponse]


def _safety(request: Request) -> DataSafety:
    return getattr(request.app.state.services, "data_safety", None) or DataSafety()


def _overview(request: Request) -> DataSafetyResponse:
    safety = _safety(request)
    repository = request.app.state.services.recording_repository
    recordings_on = safety.integrity is not None and repository is not None
    counts = repository.counts() if recordings_on else RecordingCounts()
    transcripts = safety.offsite.transcript_counts() if safety.offsite else None
    archive_run = safety.offsite.last_run if safety.offsite else None
    integrity_run = safety.integrity.last_run if safety.integrity else None
    return DataSafetyResponse(
        archive_enabled=safety.offsite is not None,
        storage=None if safety.storage is None else safety.storage.describe(),
        transcripts_archived=0 if transcripts is None else transcripts.archived,
        transcripts_pending=0 if transcripts is None else transcripts.pending,
        last_archive_run=(
            None if archive_run is None else ArchiveRunResponse.model_validate(archive_run)
        ),
        recordings_enabled=recordings_on,
        recordings_kept=counts.kept,
        recordings_archived=counts.archived,
        recordings_checked=counts.checked,
        recordings_lost=counts.lost,
        lost=[
            LostRecordingResponse(
                call_id=r.call_id, created_at=r.created_at, verified_at=r.verified_at
            )
            for r in (repository.list_lost(LOST_SHOWN) if recordings_on else ())
        ],
        last_integrity_run=(
            None if integrity_run is None else IntegrityRunResponse.model_validate(integrity_run)
        ),
        backups_enabled=safety.backups is not None,
        backup_interval_seconds=None if safety.backups is None else safety.backups.interval_seconds,
        backup_retention_days=None if safety.backups is None else safety.backups.retention_days,
        backups=[
            BackupResponse.model_validate(backup)
            for backup in (safety.backups.recent(RECENT_BACKUPS) if safety.backups else ())
        ],
    )


@router.get("", response_model=DataSafetyResponse)
async def data_safety(request: Request, _: User = Depends(_ADMINS)) -> DataSafetyResponse:
    return await run_in_threadpool(_overview, request)


@router.post("/copy", response_model=ArchiveRunResponse)
async def copy_now(request: Request, _: User = Depends(_ADMINS)) -> ArchiveRunResponse:
    """Make the pending copies off the server now."""
    offsite = _safety(request).offsite
    if offsite is None:
        raise HTTPException(status_code=409, detail="Nothing is copied off this server.")
    return ArchiveRunResponse.model_validate(await run_in_threadpool(offsite.run))


@router.post("/check", response_model=IntegrityRunResponse)
async def check_now(request: Request, _: User = Depends(_ADMINS)) -> IntegrityRunResponse:
    """Check the stored recordings now, whenever they were last checked."""
    integrity = _safety(request).integrity
    if integrity is None:
        raise HTTPException(status_code=409, detail="This server keeps no recordings.")
    return IntegrityRunResponse.model_validate(await run_in_threadpool(integrity.run, True))


@router.post("/backup", response_model=BackupResponse)
async def back_up_now(request: Request, _: User = Depends(_ADMINS)) -> BackupResponse:
    """Back the database up now."""
    backups = _safety(request).backups
    if backups is None:
        raise HTTPException(status_code=409, detail="Database backups are switched off.")
    backup = await run_in_threadpool(backups.run)
    if backup is None:
        raise HTTPException(status_code=409, detail="A backup is already running.")
    return BackupResponse.model_validate(backup)
