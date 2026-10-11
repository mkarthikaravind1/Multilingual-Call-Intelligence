"""Automatic database backups.

Every BACKUP_INTERVAL_SECONDS the database is dumped with pg_dump (custom
format), the dump is encrypted under ARCHIVE_ENCRYPTION_KEY and put in the
object storage under backups/. Backups older than BACKUP_RETENTION_DAYS are
removed. Every attempt is recorded, failed ones with the reason.

Restoring is done by hand with scripts/restore_backup.py (see
DEPLOYMENT.md): it fetches and decrypts a backup and gives it to
pg_restore.
"""

import logging
import os
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from sqlalchemy.engine import make_url

from app.observability.metrics import DATABASE_BACKUPS
from app.security.file_encryption import encrypt_file
from app.services.live_state_store import LiveStateStore
from app.services.object_storage import ObjectStorage, sha256_of_file

logger = logging.getLogger(__name__)

_SECONDS_PER_DAY = 86400
_LOCK = "database_backup"
BACKUP_PREFIX = "backups/"
_MAX_ERROR_CHARS = 500


class BackupStatus(str, Enum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class BackupError(Exception):
    pass


@dataclass(frozen=True)
class DatabaseBackup:
    started_at: float
    status: BackupStatus
    finished_at: float | None = None
    archive_key: str | None = None
    size_bytes: int | None = None
    # Of the encrypted file as stored.
    sha256: str | None = None
    error: str | None = None
    # When retention removed the file from the storage.
    removed_at: float | None = None
    # Given by the store.
    backup_id: int | None = None


class BackupRepository(ABC):
    @abstractmethod
    def add(self, backup: DatabaseBackup) -> DatabaseBackup:
        """Store a new backup; returns it with its id."""
        raise NotImplementedError

    @abstractmethod
    def save(self, backup: DatabaseBackup) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_recent(self, limit: int) -> tuple[DatabaseBackup, ...]:
        """Newest first."""
        raise NotImplementedError

    @abstractmethod
    def latest_done(self) -> DatabaseBackup | None:
        raise NotImplementedError

    @abstractmethod
    def list_expired(self, started_before: float) -> tuple[DatabaseBackup, ...]:
        """Finished backups still in the storage that started before
        started_before."""
        raise NotImplementedError


class InMemoryBackupRepository(BackupRepository):
    def __init__(self) -> None:
        self._backups: dict[int, DatabaseBackup] = {}

    def add(self, backup: DatabaseBackup) -> DatabaseBackup:
        stored = replace(backup, backup_id=len(self._backups) + 1)
        self._backups[stored.backup_id] = stored
        return stored

    def save(self, backup: DatabaseBackup) -> None:
        self._backups[backup.backup_id] = backup

    def _newest_first(self) -> list[DatabaseBackup]:
        return sorted(self._backups.values(), key=lambda b: (b.started_at, b.backup_id), reverse=True)

    def list_recent(self, limit: int) -> tuple[DatabaseBackup, ...]:
        return tuple(self._newest_first()[:limit])

    def latest_done(self) -> DatabaseBackup | None:
        return next((b for b in self._newest_first() if b.status is BackupStatus.DONE), None)

    def list_expired(self, started_before: float) -> tuple[DatabaseBackup, ...]:
        return tuple(
            b
            for b in self._newest_first()
            if b.status is BackupStatus.DONE
            and b.removed_at is None
            and b.started_at < started_before
        )


def pg_dump_command(database_url: str, pg_dump_path: str = "pg_dump") -> tuple[list[str], dict[str, str], str]:
    """The pg_dump command for DATABASE_URL (without its output file), the
    environment that carries the password (never the command line, which
    other users of the machine can read), and the database's name."""
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise BackupError("Database backups need a PostgreSQL DATABASE_URL.")
    command = [pg_dump_path, "--format=custom", "--no-owner", "--no-privileges"]
    if url.host:
        command += ["--host", url.host]
    if url.port:
        command += ["--port", str(url.port)]
    if url.username:
        command += ["--username", url.username]
    command += ["--dbname", url.database or "postgres"]
    environment = {"PGPASSWORD": url.password} if url.password else {}
    return command, environment, url.database or "postgres"


def pg_dump_to(
    database_url: str, pg_dump_path: str = "pg_dump", timeout_seconds: float = 3600.0
) -> Callable[[Path], None]:
    """A function that dumps the database into the file it is given."""
    command, environment, _ = pg_dump_command(database_url, pg_dump_path)

    def dump(target: Path) -> None:
        try:
            result = subprocess.run(
                [*command, "--file", str(target)],
                env={**os.environ, **environment},
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise BackupError(
                f"{pg_dump_path} is not installed on this server (set BACKUP_PG_DUMP_PATH)."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise BackupError(f"pg_dump did not finish in {timeout_seconds:.0f} seconds.") from exc
        if result.returncode != 0:
            raise BackupError(f"pg_dump failed: {result.stderr.strip()[-_MAX_ERROR_CHARS:]}")

    return dump


class DatabaseBackupService:
    def __init__(
        self,
        storage: ObjectStorage,
        encryption_key: bytes,
        repository: BackupRepository,
        dump: Callable[[Path], None],
        live_state: LiveStateStore,
        interval_seconds: float = 86400.0,
        retention_days: float = 14.0,
        database_name: str = "database",
        lock_seconds: float = 2 * 3600.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._storage = storage
        self._key = encryption_key
        self._repository = repository
        self._dump = dump
        self._live_state = live_state
        self._interval = interval_seconds
        self._retention_days = retention_days
        self._database_name = database_name
        self._lock_seconds = lock_seconds
        self._clock = clock

    @property
    def interval_seconds(self) -> float:
        return self._interval

    @property
    def retention_days(self) -> float:
        return self._retention_days

    def recent(self, limit: int = 10) -> tuple[DatabaseBackup, ...]:
        return self._repository.list_recent(limit)

    def latest_done(self) -> DatabaseBackup | None:
        return self._repository.latest_done()

    def run_if_due(self) -> DatabaseBackup | None:
        """Back up when the last good backup is older than the interval
        (checked often, so a restart never skips a day); then remove the
        backups past their retention."""
        latest = self._repository.latest_done()
        backup = None
        if latest is None or self._clock() - latest.started_at >= self._interval:
            backup = self.run()
        self.purge_expired()
        return backup

    def run(self) -> DatabaseBackup | None:
        """Back up now. None when another instance is already doing it."""
        token = self._live_state.acquire_lock(_LOCK, self._lock_seconds)
        if token is None:
            return None
        try:
            return self._run()
        finally:
            self._live_state.release_lock(_LOCK, token)

    def _run(self) -> DatabaseBackup:
        started_at = self._clock()
        backup = self._repository.add(DatabaseBackup(started_at, BackupStatus.RUNNING))
        stamp = datetime.fromtimestamp(started_at, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = f"{stamp}-{self._database_name}.dump.enc"
        key = BACKUP_PREFIX + name
        try:
            with tempfile.TemporaryDirectory(prefix="db-backup-") as folder:
                plain = Path(folder) / "database.dump"
                sealed = Path(folder) / name
                self._dump(plain)
                encrypt_file(plain, sealed, self._key, name)
                plain.unlink()
                size = sealed.stat().st_size
                digest = sha256_of_file(sealed)
                self._storage.put_file(key, sealed)
            copy = self._storage.stat(key)
            if copy is None or copy.size_bytes != size:
                raise BackupError("The backup is not complete in the storage.")
        except Exception as exc:
            DATABASE_BACKUPS.inc("failed")
            logger.exception("The database backup failed")
            failed = replace(
                backup,
                status=BackupStatus.FAILED,
                finished_at=self._clock(),
                error=str(exc)[:_MAX_ERROR_CHARS],
            )
            self._repository.save(failed)
            return failed
        done = replace(
            backup,
            status=BackupStatus.DONE,
            finished_at=self._clock(),
            archive_key=key,
            size_bytes=size,
            sha256=digest,
        )
        self._repository.save(done)
        DATABASE_BACKUPS.inc("done")
        logger.info("Database backup stored as %s (%d bytes)", key, size)
        return done

    def purge_expired(self) -> int:
        """Remove the backups older than the retention period, but never
        the newest good one."""
        cutoff = self._clock() - self._retention_days * _SECONDS_PER_DAY
        latest = self._repository.latest_done()
        removed = 0
        for backup in self._repository.list_expired(cutoff):
            if latest is not None and backup.backup_id == latest.backup_id:
                continue
            try:
                self._storage.delete(backup.archive_key)
            except Exception:
                logger.exception("Could not remove the backup %s", backup.archive_key)
                continue
            self._repository.save(replace(backup, removed_at=self._clock()))
            removed += 1
        if removed:
            logger.info("Removed %d expired database backups", removed)
        return removed
