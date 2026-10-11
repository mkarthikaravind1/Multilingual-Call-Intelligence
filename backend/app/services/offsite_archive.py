"""Copies of recordings and transcripts off the server, and the check that
stored recordings are still what was written.

OffsiteArchive runs every ARCHIVE_SWEEP_SECONDS. It copies each kept
recording (already encrypted, see recording_archive) and each finished
call's transcript (encrypted here, under ARCHIVE_ENCRYPTION_KEY) to the
object storage, and removes a recording's copy once retention has removed
the recording. A copy that fails is tried again at the next sweep.

RecordingIntegrityChecker runs every INTEGRITY_CHECK_INTERVAL_SECONDS. It
compares each recording's file with the SHA-256 noted when it was written.
A file that is missing or changed is restored from its copy off the
server; a copy that is missing is sent again; a recording with no good
copy left is marked lost and logged as an error.
"""

import json
import logging
import os
import re
import tempfile
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone

from app.domain.conversation import Conversation, ConversationStatus
from app.domain.post_call_summary import PostCallSummary
from app.observability.metrics import OFFSITE_COPIES, RECORDING_INTEGRITY_CHECKS
from app.security.file_encryption import encrypt_bytes
from app.services.live_state_store import LiveStateStore
from app.services.object_storage import ObjectStorage, sha256_of, sha256_of_file
from app.services.recording_archive import (
    RecordingArchive,
    RecordingIntegrity,
    RecordingRepository,
    StoredRecording,
)

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")
_ARCHIVE_LOCK = "offsite_archive"
_INTEGRITY_LOCK = "recording_integrity"
_LOCK_TTL_SECONDS = 900.0
_ARCHIVE_RUN_KEY = "offsite_archive:last_run"
_INTEGRITY_RUN_KEY = "recording_integrity:last_run"
_MAX_ERROR_CHARS = 300


@dataclass(frozen=True)
class ArchivedTranscript:
    call_id: str
    archive_key: str
    # Of the encrypted file as stored.
    sha256: str
    size_bytes: int
    archived_at: float


@dataclass(frozen=True)
class TranscriptCounts:
    archived: int = 0
    # Finished calls old enough to copy that have no copy yet.
    pending: int = 0


class TranscriptArchiveRepository(ABC):
    @abstractmethod
    def get(self, call_id: str) -> ArchivedTranscript | None:
        raise NotImplementedError

    @abstractmethod
    def save(self, transcript: ArchivedTranscript) -> None:
        raise NotImplementedError

    @abstractmethod
    def pending_call_ids(self, ended_before: float, limit: int) -> tuple[str, ...]:
        """Completed calls that ended before ended_before and have no copy
        yet, oldest first."""
        raise NotImplementedError

    @abstractmethod
    def counts(self, ended_before: float) -> TranscriptCounts:
        raise NotImplementedError


class InMemoryTranscriptArchiveRepository(TranscriptArchiveRepository):
    def __init__(self, calls: Callable[[], Iterable[Conversation]]) -> None:
        """calls: every call there is (the in-memory stores are small)."""
        self._calls = calls
        self._archived: dict[str, ArchivedTranscript] = {}

    def get(self, call_id: str) -> ArchivedTranscript | None:
        return self._archived.get(call_id)

    def save(self, transcript: ArchivedTranscript) -> None:
        self._archived[transcript.call_id] = transcript

    def _waiting(self, ended_before: float) -> list[Conversation]:
        waiting = [
            call
            for call in self._calls()
            if call.status == ConversationStatus.COMPLETED
            and call.end_time is not None
            and call.end_time < ended_before
            and call.call_id not in self._archived
        ]
        return sorted(waiting, key=lambda call: (call.end_time, call.call_id))

    def pending_call_ids(self, ended_before: float, limit: int) -> tuple[str, ...]:
        return tuple(call.call_id for call in self._waiting(ended_before)[:limit])

    def counts(self, ended_before: float) -> TranscriptCounts:
        return TranscriptCounts(len(self._archived), len(self._waiting(ended_before)))


@dataclass(frozen=True)
class ArchiveRun:
    ran_at: float
    recordings_copied: int = 0
    transcripts_copied: int = 0
    # Copies removed because retention removed their recording.
    copies_removed: int = 0
    failed: int = 0
    last_error: str | None = None
    # Why the sweep did not run, e.g. another instance is running it.
    skipped_reason: str | None = None


@dataclass(frozen=True)
class IntegrityRun:
    ran_at: float
    checked: int = 0
    ok: int = 0
    repaired: int = 0
    lost: int = 0
    skipped_reason: str | None = None


def object_key(kind: str, at: float, name: str) -> str:
    """kind/yyyy/mm/name, by the month (UTC) the thing is from."""
    when = datetime.fromtimestamp(at, tz=timezone.utc)
    return f"{kind}/{when:%Y}/{when:%m}/{_SAFE_NAME.sub('_', name)}"


def transcript_document(conversation: Conversation, summary: PostCallSummary | None) -> bytes:
    """The call's transcript as it is kept off the server: JSON, UTF-8."""
    document = {
        "format": 1,
        "call_id": conversation.call_id,
        "start_time": conversation.start_time,
        "end_time": conversation.end_time,
        "direction": None if conversation.direction is None else conversation.direction.value,
        "location_id": conversation.location_id,
        "executive_user_id": conversation.executive_user_id,
        "holds": [
            {"started_at": hold.started_at, "ended_at": hold.ended_at}
            for hold in conversation.holds
        ],
        "utterances": [
            {
                "utterance_id": u.utterance_id,
                "speaker_role": u.speaker_role.value,
                "transcript": u.transcript,
                "languages": list(u.languages),
                "start_time": u.start_time,
                "end_time": u.end_time,
                "confidence": u.confidence,
                "sentiment": None if u.sentiment is None else u.sentiment.value,
                "complaint_categories": list(u.complaint_categories),
            }
            for u in conversation.utterances
        ],
        "summary": None
        if summary is None
        else {
            "overall_summary": summary.overall_summary,
            "customer_summary": summary.customer_summary,
            "follow_up_required": summary.follow_up_required,
            "actions_promised": list(summary.actions_promised),
            "unresolved_issues": list(summary.unresolved_issues),
        },
    }
    return json.dumps(document, ensure_ascii=False, sort_keys=True).encode()


class OffsiteArchive:
    def __init__(
        self,
        storage: ObjectStorage,
        encryption_key: bytes,
        transcripts: TranscriptArchiveRepository,
        get_call: Callable[[str], Conversation],
        get_summary: Callable[[str], PostCallSummary | None],
        live_state: LiveStateStore,
        recordings: RecordingArchive | None = None,
        recording_repository: RecordingRepository | None = None,
        transcript_delay_seconds: float = 900.0,
        batch_size: int = 50,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """transcript_delay_seconds: how long after a call ends its
        transcript is copied (post-call processing may still revise it).
        recordings: None when this server keeps no recordings."""
        self._storage = storage
        self._key = encryption_key
        self._transcripts = transcripts
        self._get_call = get_call
        self._get_summary = get_summary
        self._live_state = live_state
        self._recordings = recordings
        self._recording_repository = recording_repository if recordings is not None else None
        self._delay = transcript_delay_seconds
        self._batch_size = max(1, batch_size)
        self._clock = clock

    @property
    def storage(self) -> ObjectStorage:
        return self._storage

    @property
    def last_run(self) -> ArchiveRun | None:
        raw = self._live_state.get_json(_ARCHIVE_RUN_KEY)
        return None if raw is None else ArchiveRun(**raw)

    def transcript_counts(self) -> TranscriptCounts:
        return self._transcripts.counts(self._clock() - self._delay)

    def has_copy(self, call_id: str) -> bool:
        """Whether everything of the call that is kept has its copy off
        the server: its transcript, and its recording when it has one."""
        if self._transcripts.get(call_id) is None:
            return False
        if self._recording_repository is None:
            return True
        stored = self._recording_repository.get(call_id)
        return stored is None or not stored.is_available or stored.archived_at is not None

    def run(self) -> ArchiveRun:
        token = self._live_state.acquire_lock(_ARCHIVE_LOCK, _LOCK_TTL_SECONDS)
        if token is None:
            return ArchiveRun(self._clock(), skipped_reason="Another instance is already running it.")
        try:
            run = self._run()
        finally:
            self._live_state.release_lock(_ARCHIVE_LOCK, token)
        self._live_state.set_json(_ARCHIVE_RUN_KEY, asdict(run))
        return run

    def _run(self) -> ArchiveRun:
        counts = {"recording": 0, "transcript": 0, "removed": 0, "failed": 0}
        last_error: str | None = None

        def attempt(kind: str, call_id: str, work: Callable[[], bool]) -> None:
            nonlocal last_error
            try:
                if work():
                    counts[kind] += 1
                    OFFSITE_COPIES.inc(kind, "done")
            except Exception as exc:
                counts["failed"] += 1
                OFFSITE_COPIES.inc(kind, "failed")
                last_error = f"{kind} of call {call_id}: {exc}"[:_MAX_ERROR_CHARS]
                logger.exception("Could not finish the off-site %s of call %r", kind, call_id)

        if self._recording_repository is not None:
            for stored in self._recording_repository.list_unarchived(self._batch_size):
                attempt("recording", stored.call_id, lambda s=stored: self._copy_recording(s))
            for stored in self._recording_repository.list_removed_with_copy(self._batch_size):
                attempt("removed", stored.call_id, lambda s=stored: self._remove_copy(s))
        ended_before = self._clock() - self._delay
        for call_id in self._transcripts.pending_call_ids(ended_before, self._batch_size):
            attempt("transcript", call_id, lambda c=call_id: self._copy_transcript(c))

        run = ArchiveRun(
            ran_at=self._clock(),
            recordings_copied=counts["recording"],
            transcripts_copied=counts["transcript"],
            copies_removed=counts["removed"],
            failed=counts["failed"],
            last_error=last_error,
        )
        if run.recordings_copied or run.transcripts_copied or run.copies_removed:
            logger.info(
                "Off-site copies: %d recordings, %d transcripts, %d removed",
                run.recordings_copied,
                run.transcripts_copied,
                run.copies_removed,
            )
        return run

    def _copy_recording(self, stored: StoredRecording) -> bool:
        path = self._recordings.path_of(stored)
        if not path.is_file():
            # The integrity check deals with it (and says so).
            logger.warning("The recording of call %r is not on this server", stored.call_id)
            return False
        digest = sha256_of_file(path)
        if stored.sha256 is not None and digest != stored.sha256:
            logger.error(
                "The recording of call %r is not what was written; not copying it",
                stored.call_id,
            )
            return False
        key = object_key("recordings", stored.created_at, stored.file_name)
        self._storage.put_file(key, path)
        copy = self._storage.stat(key)
        if copy is None or copy.size_bytes != path.stat().st_size:
            raise RuntimeError("the copy is not complete in the storage")
        # Read again: retention may have removed the recording meanwhile.
        current = self._recording_repository.get(stored.call_id) or stored
        self._recording_repository.save(
            replace(current, sha256=digest, archive_key=key, archived_at=self._clock())
        )
        return True

    def _remove_copy(self, stored: StoredRecording) -> bool:
        self._storage.delete(stored.archive_key)
        self._recording_repository.save(replace(stored, archive_key=None, archived_at=None))
        return True

    def _copy_transcript(self, call_id: str) -> bool:
        conversation = self._get_call(call_id)
        sealed = encrypt_bytes(
            transcript_document(conversation, self._get_summary(call_id)), self._key, call_id
        )
        at = conversation.end_time or conversation.start_time or self._clock()
        key = object_key("transcripts", at, f"{call_id}.json.enc")
        self._storage.put(key, sealed)
        self._transcripts.save(
            ArchivedTranscript(call_id, key, sha256_of(sealed), len(sealed), self._clock())
        )
        return True


class RecordingIntegrityChecker:
    def __init__(
        self,
        recordings: RecordingArchive,
        repository: RecordingRepository,
        live_state: LiveStateStore,
        storage: ObjectStorage | None = None,
        recheck_seconds: float = 86400.0,
        batch_size: int = 500,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """storage: where the copies are; None when nothing is copied off
        the server (a damaged file can then only be reported).
        recheck_seconds: how long a checked recording is left alone."""
        self._recheck_seconds = recheck_seconds
        self._recordings = recordings
        self._repository = repository
        self._live_state = live_state
        self._storage = storage
        self._batch_size = max(1, batch_size)
        self._clock = clock

    @property
    def last_run(self) -> IntegrityRun | None:
        raw = self._live_state.get_json(_INTEGRITY_RUN_KEY)
        return None if raw is None else IntegrityRun(**raw)

    def run(self, everything: bool = False) -> IntegrityRun:
        """Check the recordings that are due (everything: all of them, up
        to the batch size, however recently they were checked)."""
        token = self._live_state.acquire_lock(_INTEGRITY_LOCK, _LOCK_TTL_SECONDS)
        if token is None:
            return IntegrityRun(
                self._clock(), skipped_reason="Another instance is already running it."
            )
        try:
            due_before = None if everything else self._clock() - self._recheck_seconds
            results = [
                self._check(stored)
                for stored in self._repository.list_to_verify(self._batch_size, due_before)
            ]
        finally:
            self._live_state.release_lock(_INTEGRITY_LOCK, token)
        run = IntegrityRun(
            ran_at=self._clock(),
            checked=len(results),
            ok=results.count(RecordingIntegrity.OK),
            repaired=results.count(RecordingIntegrity.REPAIRED),
            lost=results.count(RecordingIntegrity.LOST),
        )
        self._live_state.set_json(_INTEGRITY_RUN_KEY, asdict(run))
        if run.repaired or run.lost:
            logger.warning(
                "Recording check: %d checked, %d repaired, %d lost",
                run.checked,
                run.repaired,
                run.lost,
            )
        return run

    def _check(self, stored: StoredRecording) -> RecordingIntegrity:
        try:
            checked = self._checked(stored)
        except Exception:
            # e.g. the storage cannot be reached: not a verdict on the file.
            logger.exception("Could not check the recording of call %r", stored.call_id)
            RECORDING_INTEGRITY_CHECKS.inc("error")
            return stored.integrity or RecordingIntegrity.OK
        # Read again: retention or the copier may have changed it meanwhile.
        current = self._repository.get(stored.call_id) or stored
        if current.is_available:
            self._repository.save(
                replace(
                    current,
                    sha256=checked.sha256,
                    archive_key=checked.archive_key,
                    archived_at=checked.archived_at,
                    verified_at=self._clock(),
                    integrity=checked.integrity,
                )
            )
        RECORDING_INTEGRITY_CHECKS.inc(checked.integrity.value)
        if checked.integrity is RecordingIntegrity.LOST:
            logger.error(
                "The recording of call %r is missing or changed and cannot be restored",
                stored.call_id,
            )
        return checked.integrity

    def _checked(self, stored: StoredRecording) -> StoredRecording:
        path = self._recordings.path_of(stored)
        local = sha256_of_file(path) if path.is_file() else None
        # A recording from before checksums were kept: what is there now
        # is taken as written.
        expected = stored.sha256 or local

        if local is not None and local == expected:
            if stored.archive_key is None or self._storage is None:
                return replace(stored, sha256=expected, integrity=RecordingIntegrity.OK)
            copy = self._storage.stat(stored.archive_key)
            if copy is not None and copy.size_bytes == path.stat().st_size:
                return replace(stored, sha256=expected, integrity=RecordingIntegrity.OK)
            # The copy is gone or cut short: the copier sends it again.
            logger.warning("The off-site copy of call %r is missing; sending it again", stored.call_id)
            return replace(
                stored,
                sha256=expected,
                archive_key=None,
                archived_at=None,
                integrity=RecordingIntegrity.REPAIRED,
            )

        if expected is not None and stored.archive_key and self._storage is not None:
            if self._restore(stored, expected):
                return replace(stored, integrity=RecordingIntegrity.REPAIRED)
        return replace(stored, integrity=RecordingIntegrity.LOST)

    def _restore(self, stored: StoredRecording, expected: str) -> bool:
        """Put the copy from the storage back in place, when it is the
        file that was written."""
        path = self._recordings.path_of(stored)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(dir=path.parent, suffix=".restore")
        os.close(handle)
        try:
            if not self._storage.get_file(stored.archive_key, name):
                return False
            if sha256_of_file(name) != expected:
                return False
            os.replace(name, path)
            logger.warning("Restored the recording of call %r from its off-site copy", stored.call_id)
            return True
        finally:
            if os.path.exists(name):
                os.remove(name)
