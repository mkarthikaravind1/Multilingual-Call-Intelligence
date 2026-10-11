"""Fetch a database backup from the archive storage and decrypt it.

Uses the storage and the key in the environment (.env): ARCHIVE_STORAGE_*,
ARCHIVE_S3_* and ARCHIVE_ENCRYPTION_KEY, the same ones the backups were
made with. From backend/:

    python -m scripts.restore_backup --list
    python -m scripts.restore_backup --latest --out restore.dump
    python -m scripts.restore_backup --key backups/20261011T020000Z-calls.dump.enc --out restore.dump

The result is a pg_dump custom-format file. Look inside it, then restore it
into an EMPTY database (never over the live one):

    pg_restore --list restore.dump
    createdb -h HOST -U USER restored_calls
    pg_restore --no-owner -h HOST -U USER -d restored_calls restore.dump

Then point DATABASE_URL at the restored database and start the backend.
"""

import argparse
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from app.core.config import get_settings
from app.security.file_encryption import DecryptionError, decrypt_file
from app.services.database_backup import BACKUP_PREFIX
from app.services.object_storage import ObjectStorage, StorageError, build_object_storage
from app.services.recording_archive import RecordingError, parse_key


def restore(storage: ObjectStorage, key: bytes, object_key: str, out: Path) -> None:
    """Fetch object_key and write its decrypted dump to out."""
    with tempfile.TemporaryDirectory(prefix="db-restore-") as folder:
        sealed = Path(folder) / "backup.enc"
        if not storage.get_file(object_key, sealed):
            raise StorageError(f"There is no backup {object_key!r} in the storage.")
        decrypt_file(sealed, out, key, PurePosixPath(object_key).name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch and decrypt a database backup.")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--list", action="store_true", help="list the backups in the storage")
    choice.add_argument("--latest", action="store_true", help="fetch the newest backup")
    choice.add_argument("--key", help="fetch this backup (as --list prints it)")
    parser.add_argument("--out", type=Path, help="where to write the decrypted dump")
    args = parser.parse_args(argv)

    settings = get_settings()
    try:
        storage = build_object_storage(settings)
        if storage is None:
            print("ARCHIVE_STORAGE_PROVIDER is none: there is no storage to read from.")
            return 2
        backups = storage.list(BACKUP_PREFIX)
        if args.list:
            for item in backups:
                when = datetime.fromtimestamp(item.modified_at, tz=timezone.utc)
                print(f"{item.key}\t{item.size_bytes} bytes\t{when:%Y-%m-%d %H:%M} UTC")
            if not backups:
                print(f"No backups in {storage.describe()}.")
            return 0
        if args.out is None:
            parser.error("--out is needed to fetch a backup")
        if args.latest and not backups:
            print(f"No backups in {storage.describe()}.")
            return 1
        # Their names start with the time they were made, so the last is the newest.
        object_key = backups[-1].key if args.latest else args.key
        restore(
            storage,
            parse_key(settings.archive_encryption_key, "ARCHIVE_ENCRYPTION_KEY"),
            object_key,
            args.out,
        )
    except (StorageError, RecordingError, DecryptionError) as error:
        print(f"Could not fetch the backup: {error}")
        return 1
    print(f"Wrote {args.out} from {object_key}.")
    print(f"Check it:   pg_restore --list {args.out}")
    print(f"Restore it: pg_restore --no-owner -d <an EMPTY database> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
