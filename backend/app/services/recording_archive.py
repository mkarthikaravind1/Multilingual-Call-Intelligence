"""Call recordings kept on disk, encrypted, for a set number of days.

A recording is the call's audio as it was streamed: a WAV file (one channel
for a mixed stream, two when the two sides arrive separately: the caller on
the left), encrypted whole with AES-256-GCM under the key in
RECORDING_ENCRYPTION_KEY. The call's id is bound into the encryption, so a
file cannot be passed off as another call's.

Files are on this instance's disk (RECORDING_DIR): with several API
instances the folder must be shared between them. A file is removed only by
the retention sweep, once its call's keep-until date has passed.
"""

import base64
import binascii
import io
import logging
import os
import re
import time
import wave
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, replace
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


def parse_key(value: str) -> bytes:
    """The 32-byte key in RECORDING_ENCRYPTION_KEY (base64). Raises
    RecordingError when it is missing or not a 32-byte key."""
    text = (value or "").strip()
    if not text:
        raise RecordingError("RECORDING_ENCRYPTION_KEY is not set.")
    try:
        key = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise RecordingError("RECORDING_ENCRYPTION_KEY is not valid base64.") from exc
    if len(key) != KEY_BYTES:
        raise RecordingError(
            f"RECORDING_ENCRYPTION_KEY must be {KEY_BYTES} random bytes in base64 "
            f"(it holds {len(key)})."
        )
    return key


def generate_key() -> str:
    """A new key, as RECORDING_ENCRYPTION_KEY takes it."""
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

    def save(self, call_id: str, recording: CallRecording) -> StoredRecording | None:
        """Encrypt the call's audio and keep it. None when there is nothing
        to keep, or the call already has a recording (the first is kept:
        e.g. a stream that reconnected)."""
        if not recording.tracks or not any(recording.tracks.values()):
            return None
        if self._repository.get(call_id) is not None:
            logger.info("Call %r already has a recording; keeping the first", call_id)
            return None

        wav, channels = to_wav(recording)
        nonce = os.urandom(_NONCE_BYTES)
        encrypted = nonce + self._cipher.encrypt(nonce, wav, call_id.encode())
        file_name = f"{_SAFE_NAME.sub('_', call_id)}.wav.enc"
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._directory / file_name
        # Written under another name first, so a crash never leaves half a file.
        partial = path.with_suffix(".part")
        partial.write_bytes(encrypted)
        os.replace(partial, path)

        now = self._clock()
        stored = StoredRecording(
            call_id=call_id,
            file_name=file_name,
            duration_seconds=max(recording.duration(track) for track in recording.tracks),
            size_bytes=len(encrypted),
            sample_rate=recording.sample_rate,
            channels=channels,
            created_at=now,
            delete_after=now + self._retention_seconds,
        )
        self._repository.save(stored)
        return stored

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
