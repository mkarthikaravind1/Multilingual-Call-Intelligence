"""Call recordings kept on disk, encrypted, for a set number of days.

A recording is the call's audio as it was streamed: a WAV file (one channel
for a mixed stream, two when the two sides arrive separately: the caller on
the left), encrypted whole with AES-256-GCM under the key in
RECORDING_ENCRYPTION_KEY. The call's id is bound into the encryption, so a
file cannot be passed off as another call's.

Files are on this instance's disk (RECORDING_DIR): with several API
instances the folder must be shared between them. A file is removed only by
the retention sweep, once its call's keep-until date has passed.

A call whose audio stream dropped and came back is recorded in parts: each
later part is joined to the end of the file. The silence while the stream
was away is not in the recording.

Each file's SHA-256 is noted when it is written, so that a later check can
tell a file that was damaged or swapped (see offsite_archive, which also
copies the files off the server).
"""

import base64
import binascii
import hashlib
import io
import logging
import os
import re
import threading
import time
import wave
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.services.call_recording_store import CallRecording

logger = logging.getLogger(__name__)

KEY_BYTES = 32
_NONCE_BYTES = 12
_SECONDS_PER_DAY = 86400
# The caller's side first (left), then what the caller hears (right).
_TRACK_ORDER = ("inbound", "outbound")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


class RecordingError(Exception):
    """A recording that cannot be kept or read (the message says why)."""


class RecordingNotFoundError(RecordingError):
    pass


class RecordingIntegrity(str, Enum):
    # The file is as it was written (and so is its copy off the server).
    OK = "ok"
    # One copy was missing or changed and was made good from the other.
    REPAIRED = "repaired"
    # The file is missing or changed and there is no good copy to restore.
    LOST = "lost"


@dataclass(frozen=True)
class RecordingCounts:
    # Recordings kept now (not yet removed by retention).
    kept: int = 0
    # Of those, copied off the server.
    archived: int = 0
    # Of those, checked at least once.
    checked: int = 0
    lost: int = 0


@dataclass(frozen=True)
class StoredRecording:
    call_id: str
    file_name: str
    duration_seconds: float
    size_bytes: int
    sample_rate: int
    channels: int
    created_at: float
    # The file is removed once this has passed.
    delete_after: float
    # When the retention sweep removed the file; None while it is kept.
    deleted_at: float | None = None
    # SHA-256 of the encrypted file as written; None for a recording made
    # before checksums were kept (noted at its first check).
    sha256: str | None = None
    # Where its copy off the server is, and since when; None: not copied.
    archive_key: str | None = None
    archived_at: float | None = None
    # When the file was last compared with its checksum, and the result.
    verified_at: float | None = None
    integrity: RecordingIntegrity | None = None

    @property
    def is_available(self) -> bool:
        return self.deleted_at is None


@dataclass(frozen=True)
class RecordingPlay:
    call_id: str
    user_id: str
    played_at: float


class RecordingRepository(ABC):
    @abstractmethod
    def save(self, recording: StoredRecording) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, call_id: str) -> StoredRecording | None:
        raise NotImplementedError

    @abstractmethod
    def list_expired(self, now: float) -> tuple[StoredRecording, ...]:
        """Recordings still kept whose delete_after has passed."""
        raise NotImplementedError

    @abstractmethod
    def add_play(self, play: RecordingPlay) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_plays(self, call_id: str) -> tuple[RecordingPlay, ...]:
        """Oldest first."""
        raise NotImplementedError

    @abstractmethod
    def list_unarchived(self, limit: int) -> tuple[StoredRecording, ...]:
        """Recordings kept that have no copy off the server, oldest first."""
        raise NotImplementedError

    @abstractmethod
    def list_to_verify(
        self, limit: int, verified_before: float | None = None
    ) -> tuple[StoredRecording, ...]:
        """Recordings kept that were never checked or last checked before
        verified_before (None: all of them), the never-checked first, then
        the longest unchecked."""
        raise NotImplementedError

    @abstractmethod
    def list_removed_with_copy(self, limit: int) -> tuple[StoredRecording, ...]:
        """Recordings removed by retention whose copy off the server is
        still there."""
        raise NotImplementedError

    @abstractmethod
    def list_lost(self, limit: int) -> tuple[StoredRecording, ...]:
        """Recordings kept whose last check found them lost, newest first."""
        raise NotImplementedError

    @abstractmethod
    def counts(self) -> RecordingCounts:
        raise NotImplementedError


class InMemoryRecordingRepository(RecordingRepository):
    def __init__(self) -> None:
        self._recordings: dict[str, StoredRecording] = {}
        self._plays: list[RecordingPlay] = []

    def save(self, recording: StoredRecording) -> None:
        self._recordings[recording.call_id] = recording

    def get(self, call_id: str) -> StoredRecording | None:
        return self._recordings.get(call_id)

    def list_expired(self, now: float) -> tuple[StoredRecording, ...]:
        return tuple(
            r for r in self._recordings.values() if r.is_available and r.delete_after <= now
        )

    def add_play(self, play: RecordingPlay) -> None:
        self._plays.append(play)

    def list_plays(self, call_id: str) -> tuple[RecordingPlay, ...]:
        return tuple(p for p in self._plays if p.call_id == call_id)

    def _kept(self) -> list[StoredRecording]:
        return [r for r in self._recordings.values() if r.is_available]

    def list_unarchived(self, limit: int) -> tuple[StoredRecording, ...]:
        waiting = [r for r in self._kept() if r.archived_at is None]
        return tuple(sorted(waiting, key=lambda r: r.created_at)[:limit])

    def list_to_verify(
        self, limit: int, verified_before: float | None = None
    ) -> tuple[StoredRecording, ...]:
        due = [
            r
            for r in self._kept()
            if verified_before is None or r.verified_at is None or r.verified_at < verified_before
        ]
        return tuple(
            sorted(due, key=lambda r: (r.verified_at is not None, r.verified_at or 0.0))[:limit]
        )

    def list_removed_with_copy(self, limit: int) -> tuple[StoredRecording, ...]:
        return tuple(
            [r for r in self._recordings.values() if not r.is_available and r.archive_key][:limit]
        )

    def list_lost(self, limit: int) -> tuple[StoredRecording, ...]:
        lost = [r for r in self._kept() if r.integrity is RecordingIntegrity.LOST]
        return tuple(sorted(lost, key=lambda r: r.created_at, reverse=True)[:limit])

    def counts(self) -> RecordingCounts:
        kept = self._kept()
        return RecordingCounts(
            kept=len(kept),
            archived=sum(1 for r in kept if r.archived_at is not None),
            checked=sum(1 for r in kept if r.verified_at is not None),
            lost=sum(1 for r in kept if r.integrity is RecordingIntegrity.LOST),
        )


def parse_key(value: str, setting: str = "RECORDING_ENCRYPTION_KEY") -> bytes:
    """The 32-byte key (base64) in the named setting. Raises
    RecordingError when it is missing or not a 32-byte key."""
    text = (value or "").strip()
    if not text:
        raise RecordingError(f"{setting} is not set.")
    try:
        key = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise RecordingError(f"{setting} is not valid base64.") from exc
    if len(key) != KEY_BYTES:
        raise RecordingError(
            f"{setting} must be {KEY_BYTES} random bytes in base64 (it holds {len(key)})."
        )
    return key


def generate_key() -> str:
    """A new key, as RECORDING_ENCRYPTION_KEY and ARCHIVE_ENCRYPTION_KEY take it."""
    return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode()


def to_wav(recording: CallRecording) -> tuple[bytes, int]:
    """The recording as a WAV file, and its number of channels."""
    if set(_TRACK_ORDER) <= set(recording.tracks):
        left, right = (bytes(recording.tracks[track]) for track in _TRACK_ORDER)
        length = max(len(left), len(right))
        left, right = left.ljust(length, b"\x00"), right.ljust(length, b"\x00")
        # Interleave the two sides' 16-bit samples.
        frames = bytearray(length * 2)
        frames[0::4], frames[1::4] = left[0::2], left[1::2]
        frames[2::4], frames[3::4] = right[0::2], right[1::2]
        channels, pcm = 2, bytes(frames)
    else:
        channels, pcm = 1, bytes(next(iter(recording.tracks.values())))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(recording.sample_rate)
        out.writeframes(pcm)
    return buffer.getvalue(), channels


class RecordingArchive:
    def __init__(
        self,
        repository: RecordingRepository,
        directory: str | Path,
        key: bytes,
        retention_days: float = 90.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if len(key) != KEY_BYTES:
            raise RecordingError(f"The recording key must be {KEY_BYTES} bytes.")
        self._repository = repository
        self._directory = Path(directory)
        self._cipher = AESGCM(key)
        self._retention_seconds = retention_days * _SECONDS_PER_DAY
        self._clock = clock
        # One part of a call is written at a time: two parts arriving
        # together would each join the file the other is replacing.
        self._writing = threading.Lock()

    def save(self, call_id: str, recording: CallRecording) -> StoredRecording | None:
        """Encrypt the call's audio and keep it. A call that already has a
        recording (its stream reconnected) gets this audio joined to its
        end. None when there is nothing to keep, or it cannot be joined."""
        if not recording.tracks or not any(recording.tracks.values()):
            return None
        wav, channels = to_wav(recording)
        with self._writing:
            existing = self._repository.get(call_id)
            if existing is not None:
                return self._join(existing, recording, wav, channels)
            now = self._clock()
            return self._write(
                StoredRecording(
                    call_id=call_id,
                    file_name=f"{_SAFE_NAME.sub('_', call_id)}.wav.enc",
                    duration_seconds=0.0,
                    size_bytes=0,
                    sample_rate=recording.sample_rate,
                    channels=channels,
                    created_at=now,
                    delete_after=now + self._retention_seconds,
                ),
                wav,
            )

    def _write(self, stored: StoredRecording, wav: bytes) -> StoredRecording:
        """Encrypt wav into the recording's file and record what is there."""
        nonce = os.urandom(_NONCE_BYTES)
        encrypted = nonce + self._cipher.encrypt(nonce, wav, stored.call_id.encode())
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._directory / stored.file_name
        # Written under another name first, so a crash never leaves half a file.
        partial = path.with_suffix(".part")
        partial.write_bytes(encrypted)
        os.replace(partial, path)
        with wave.open(io.BytesIO(wav), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
        stored = replace(
            stored,
            duration_seconds=duration,
            size_bytes=len(encrypted),
            sha256=hashlib.sha256(encrypted).hexdigest(),
            # A changed file is copied off the server and checked afresh.
            archived_at=None,
            verified_at=None,
            integrity=None,
        )
        self._repository.save(stored)
        return stored

    def _join(
        self, existing: StoredRecording, recording: CallRecording, wav: bytes, channels: int
    ) -> StoredRecording | None:
        """Put a later part of the call after what is already recorded."""
        call_id = existing.call_id
        if not existing.is_available:
            return None  # removed by retention: nothing comes back
        if (existing.sample_rate, existing.channels) != (recording.sample_rate, channels):
            logger.warning(
                "A later part of call %r is in another format; keeping what is recorded",
                call_id,
            )
            return None
        try:
            encrypted = (self._directory / existing.file_name).read_bytes()
            earlier = self._cipher.decrypt(
                encrypted[:_NONCE_BYTES], encrypted[_NONCE_BYTES:], call_id.encode()
            )
        except (OSError, InvalidTag):
            logger.exception(
                "The recording of call %r cannot be read; its later part is not kept", call_id
            )
            return None
        buffer = io.BytesIO()
        with wave.open(io.BytesIO(earlier), "rb") as first, wave.open(
            io.BytesIO(wav), "rb"
        ) as second, wave.open(buffer, "wb") as out:
            out.setparams(first.getparams())
            out.writeframes(first.readframes(first.getnframes()))
            out.writeframes(second.readframes(second.getnframes()))
        logger.info("Joined a later part to the recording of call %r", call_id)
        return self._write(existing, buffer.getvalue())

    def path_of(self, stored: StoredRecording) -> Path:
        """Where the recording's encrypted file is (or should be)."""
        return self._directory / stored.file_name

    def get(self, call_id: str) -> StoredRecording | None:
        return self._repository.get(call_id)

    def read(self, call_id: str, user_id: str) -> bytes:
        """The call's recording as a WAV file, for user_id to listen to
        (each read is logged). Raises RecordingNotFoundError when there is
        none (any more), RecordingError when it cannot be decrypted."""
        stored = self._repository.get(call_id)
        if stored is None or not stored.is_available:
            raise RecordingNotFoundError(f"Call {call_id!r} has no recording.")
        path = self._directory / stored.file_name
        try:
            encrypted = path.read_bytes()
        except FileNotFoundError as exc:
            raise RecordingNotFoundError(
                f"The recording of call {call_id!r} is not on this server."
            ) from exc
        try:
            wav = self._cipher.decrypt(
                encrypted[:_NONCE_BYTES], encrypted[_NONCE_BYTES:], call_id.encode()
            )
        except InvalidTag as exc:
            raise RecordingError(
                f"The recording of call {call_id!r} cannot be decrypted: the key has "
                "changed or the file is damaged."
            ) from exc
        self._repository.add_play(RecordingPlay(call_id, user_id, self._clock()))
        logger.info("Recording of call %r read by user %r", call_id, user_id)
        return wav

    def plays(self, call_id: str) -> tuple[RecordingPlay, ...]:
        return self._repository.list_plays(call_id)

    def purge_expired(self) -> int:
        """Remove the recordings whose keep-until date has passed. Returns
        how many were removed."""
        now = self._clock()
        removed = 0
        for stored in self._repository.list_expired(now):
            try:
                (self._directory / stored.file_name).unlink(missing_ok=True)
            except OSError:
                # Left for the next sweep, still marked as kept.
                logger.exception("Could not remove the recording of call %r", stored.call_id)
                continue
            self._repository.save(replace(stored, deleted_at=now))
            removed += 1
        if removed:
            logger.info("Removed %d expired call recordings", removed)
        return removed
