"""Where copies leave the server for: an S3-compatible bucket, or a folder.

Recordings, transcripts and database backups are copied here so that losing
the server does not lose them. Everything put here is already encrypted
(see recording_archive and file_encryption): the storage provider holds
files it cannot read.

"s3" works with anything that speaks the S3 API (Amazon S3, Cloudflare R2,
Backblaze B2, MinIO): ARCHIVE_S3_ENDPOINT_URL names the service when it is
not Amazon's. "local" is a folder, for trying the whole path without an
account, or for a network share that is itself backed up.
"""

import hashlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.core.config import Settings

_CHUNK_BYTES = 1024 * 1024


class StorageError(Exception):
    """The storage could not be reached, or refused (the message says why)."""


class StorageNotConfiguredError(StorageError):
    pass


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    # Epoch seconds.
    modified_at: float


def sha256_of_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while chunk := source.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ObjectStorage(ABC):
    """Keys are "/"-separated paths, e.g. recordings/2026/10/call-1.wav.enc.
    Every method raises StorageError when the storage fails."""

    @abstractmethod
    def put(self, key: str, data: bytes) -> None:
        raise NotImplementedError

    @abstractmethod
    def put_file(self, key: str, path: str | Path) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, key: str) -> bytes | None:
        """None when there is no such object."""
        raise NotImplementedError

    @abstractmethod
    def get_file(self, key: str, path: str | Path) -> bool:
        """Write the object to path. False when there is no such object."""
        raise NotImplementedError

    @abstractmethod
    def stat(self, key: str) -> StoredObject | None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        """Removing an object that is not there is not an error."""
        raise NotImplementedError

    @abstractmethod
    def list(self, prefix: str) -> tuple[StoredObject, ...]:
        """Every object whose key starts with prefix, by key."""
        raise NotImplementedError

    @abstractmethod
    def describe(self) -> str:
        """Where this is, for people: "S3 bucket calls-archive"."""
        raise NotImplementedError


def _safe_key(key: str) -> PurePosixPath:
    path = PurePosixPath(key)
    if not key or path.is_absolute() or ".." in path.parts:
        raise StorageError(f"Not a usable storage key: {key!r}.")
    return path


class LocalFolderStorage(ObjectStorage):
    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)

    def _path(self, key: str) -> Path:
        return self._directory.joinpath(*_safe_key(key).parts)

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Written under another name first, so a crash never leaves half a file.
            partial = path.with_name(path.name + ".part")
            partial.write_bytes(data)
            os.replace(partial, path)
        except OSError as exc:
            raise StorageError(f"Could not write {key!r}: {exc}") from exc

    def put_file(self, key: str, path: str | Path) -> None:
        target = self._path(key)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".part")
            with open(path, "rb") as source, open(partial, "wb") as out:
                while chunk := source.read(_CHUNK_BYTES):
                    out.write(chunk)
            os.replace(partial, target)
        except OSError as exc:
            raise StorageError(f"Could not write {key!r}: {exc}") from exc

    def get(self, key: str) -> bytes | None:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StorageError(f"Could not read {key!r}: {exc}") from exc

    def get_file(self, key: str, path: str | Path) -> bool:
        try:
            with open(self._path(key), "rb") as source, open(path, "wb") as out:
                while chunk := source.read(_CHUNK_BYTES):
                    out.write(chunk)
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise StorageError(f"Could not read {key!r}: {exc}") from exc

    def stat(self, key: str) -> StoredObject | None:
        try:
            info = self._path(key).stat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StorageError(f"Could not read {key!r}: {exc}") from exc
        return StoredObject(key, info.st_size, info.st_mtime)

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(f"Could not remove {key!r}: {exc}") from exc

    def list(self, prefix: str) -> tuple[StoredObject, ...]:
        found = []
        try:
            for path in self._directory.rglob("*"):
                if not path.is_file() or path.name.endswith(".part"):
                    continue
                key = path.relative_to(self._directory).as_posix()
                if key.startswith(prefix):
                    info = path.stat()
                    found.append(StoredObject(key, info.st_size, info.st_mtime))
        except OSError as exc:
            raise StorageError(f"Could not list {prefix!r}: {exc}") from exc
        return tuple(sorted(found, key=lambda item: item.key))

    def describe(self) -> str:
        return f"folder {self._directory}"


class S3Storage(ObjectStorage):
    """An S3-compatible bucket. client: a boto3 S3 client (tests pass one
    that answers from memory)."""

    def __init__(self, client, bucket: str, prefix: str = "") -> None:
        self._client = client
        self._bucket = bucket
        self._prefix = prefix.strip("/")

    def _key(self, key: str) -> str:
        key = _safe_key(key).as_posix()
        return f"{self._prefix}/{key}" if self._prefix else key

    def put(self, key: str, data: bytes) -> None:
        try:
            self._client.put_object(Bucket=self._bucket, Key=self._key(key), Body=data)
        except Exception as exc:
            raise StorageError(f"Could not write {key!r}: {exc}") from exc

    def put_file(self, key: str, path: str | Path) -> None:
        try:
            self._client.upload_file(str(path), self._bucket, self._key(key))
        except Exception as exc:
            raise StorageError(f"Could not write {key!r}: {exc}") from exc

    def get(self, key: str) -> bytes | None:
        try:
            return self._client.get_object(Bucket=self._bucket, Key=self._key(key))["Body"].read()
        except Exception as exc:
            if _is_missing(exc):
                return None
            raise StorageError(f"Could not read {key!r}: {exc}") from exc

    def get_file(self, key: str, path: str | Path) -> bool:
        try:
            self._client.download_file(self._bucket, self._key(key), str(path))
            return True
        except Exception as exc:
            if _is_missing(exc):
                return False
            raise StorageError(f"Could not read {key!r}: {exc}") from exc

    def stat(self, key: str) -> StoredObject | None:
        try:
            head = self._client.head_object(Bucket=self._bucket, Key=self._key(key))
        except Exception as exc:
            if _is_missing(exc):
                return None
            raise StorageError(f"Could not read {key!r}: {exc}") from exc
        return StoredObject(key, int(head["ContentLength"]), head["LastModified"].timestamp())

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=self._key(key))
        except Exception as exc:
            raise StorageError(f"Could not remove {key!r}: {exc}") from exc

    def list(self, prefix: str) -> tuple[StoredObject, ...]:
        found = []
        strip = len(self._prefix) + 1 if self._prefix else 0
        try:
            pages = self._client.get_paginator("list_objects_v2").paginate(
                Bucket=self._bucket, Prefix=self._key(prefix) if prefix else self._prefix
            )
            for page in pages:
                for item in page.get("Contents", ()):
                    found.append(
                        StoredObject(
                            item["Key"][strip:], int(item["Size"]), item["LastModified"].timestamp()
                        )
                    )
        except Exception as exc:
            raise StorageError(f"Could not list {prefix!r}: {exc}") from exc
        return tuple(sorted(found, key=lambda item: item.key))

    def describe(self) -> str:
        return f"S3 bucket {self._bucket}" + (f" under {self._prefix}/" if self._prefix else "")


def _is_missing(exc: Exception) -> bool:
    """Whether an S3 error says the object is not there."""
    response = getattr(exc, "response", None) or {}
    code = str(response.get("Error", {}).get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404


def build_object_storage(settings: Settings) -> ObjectStorage | None:
    """The storage ARCHIVE_STORAGE_PROVIDER names; None for "none". Raises
    StorageNotConfiguredError when it is named but not filled in."""
    provider = settings.archive_storage_provider.strip().lower()
    if provider in ("", "none"):
        return None
    if provider == "local":
        if not settings.archive_storage_local_dir.strip():
            raise StorageNotConfiguredError("ARCHIVE_STORAGE_LOCAL_DIR is not set.")
        return LocalFolderStorage(settings.archive_storage_local_dir)
    if provider == "s3":
        missing = [
            name
            for name, value in (
                ("ARCHIVE_S3_BUCKET", settings.archive_s3_bucket),
                ("ARCHIVE_S3_ACCESS_KEY_ID", settings.archive_s3_access_key_id),
                ("ARCHIVE_S3_SECRET_ACCESS_KEY", settings.archive_s3_secret_access_key),
            )
            if not value.strip()
        ]
        if missing:
            raise StorageNotConfiguredError(f"{', '.join(missing)} must be set for S3 storage.")
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=settings.archive_s3_endpoint_url.strip() or None,
            region_name=settings.archive_s3_region.strip() or None,
            aws_access_key_id=settings.archive_s3_access_key_id.strip(),
            aws_secret_access_key=settings.archive_s3_secret_access_key.strip(),
            config=Config(
                connect_timeout=10,
                read_timeout=60,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        return S3Storage(client, settings.archive_s3_bucket.strip(), settings.archive_key_prefix)
    raise StorageNotConfiguredError(
        f"Unknown ARCHIVE_STORAGE_PROVIDER {settings.archive_storage_provider!r}: "
        "use none, local or s3."
    )
