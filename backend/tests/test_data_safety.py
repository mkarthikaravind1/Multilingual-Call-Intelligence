"""Copies off the server, the recording check and database backups: what is
stored where (and that it is encrypted), that a damaged or missing file is
found and restored, backups and their retention, restoring, the settings,
and who may look."""

import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentLabel, SentimentResult
from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.core.config import Settings
from app.core.production_checks import configuration_problems
from app.domain.conversation import Conversation
from app.domain.user import User, UserRole
from app.domain.utterance import SpeakerRole, Utterance
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import build_session_factory
from app.infrastructure.database.repositories.conversation_repository import (
    PostgresConversationRepository,
)
from app.infrastructure.database.repositories.data_safety_repositories import (
    PostgresBackupRepository,
    PostgresTranscriptArchiveRepository,
)
from app.infrastructure.database.repositories.recording_repository import (
    PostgresRecordingRepository,
)
from app.security.file_encryption import (
    DecryptionError,
    decrypt_bytes,
    decrypt_file,
    encrypt_bytes,
    encrypt_file,
)
from app.security.jwt import create_access_token
from app.services.call_recording_store import CallRecording
from app.services.database_backup import (
    BackupError,
    BackupStatus,
    DatabaseBackupService,
    InMemoryBackupRepository,
    pg_dump_command,
    pg_dump_to,
)
from app.services.in_memory_conversation_repository import InMemoryConversationRepository
from app.services.live_state_store import InMemoryLiveStateStore
from app.services.object_storage import (
    LocalFolderStorage,
    S3Storage,
    StorageError,
    StorageNotConfiguredError,
    build_object_storage,
    sha256_of,
)
from app.services.offsite_archive import (
    InMemoryTranscriptArchiveRepository,
    OffsiteArchive,
    RecordingIntegrityChecker,
    object_key,
)
from app.services.recording_archive import (
    InMemoryRecordingRepository,
    RecordingArchive,
    RecordingIntegrity,
    generate_key,
    parse_key,
)
from scripts import restore_backup

DAY = 86400.0
KEY = parse_key(generate_key())
OTHER_KEY = parse_key(generate_key())
# 11 October 2026, 10:00 UTC.
NOW = datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc).timestamp()


class _Clock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _session_factory(request):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    request.addfinalizer(engine.dispose)
    return build_session_factory(engine)


# ---- Encryption of what leaves the server ----


@pytest.mark.parametrize("size", [0, 1, 1024, 1024 * 1024, 2 * 1024 * 1024 + 17])
def test_what_is_encrypted_comes_back_whole_at_any_size(size):
    data = bytes(range(256)) * (size // 256) + bytes(size % 256)

    sealed = encrypt_bytes(data, KEY, "a.json")

    assert decrypt_bytes(sealed, KEY, "a.json") == data
    assert len(sealed) > len(data)
    if size >= 1024:
        assert data[:64] not in sealed


def test_the_same_content_is_encrypted_differently_each_time():
    assert encrypt_bytes(b"same", KEY, "a") != encrypt_bytes(b"same", KEY, "a")


def test_another_key_another_name_or_a_changed_file_cannot_be_read():
    sealed = encrypt_bytes(b"x" * 3_000_000, KEY, "backup-1")

    with pytest.raises(DecryptionError):
        decrypt_bytes(sealed, OTHER_KEY, "backup-1")
    with pytest.raises(DecryptionError):
        decrypt_bytes(sealed, KEY, "backup-2")
    flipped = bytearray(sealed)
    flipped[len(sealed) // 2] ^= 1
    with pytest.raises(DecryptionError):
        decrypt_bytes(bytes(flipped), KEY, "backup-1")
    with pytest.raises(DecryptionError):
        decrypt_bytes(b"not one of ours", KEY, "backup-1")


def test_a_file_cut_short_or_with_a_piece_missing_is_refused():
    sealed = encrypt_bytes(b"y" * 3_000_000, KEY, "backup-1")
    piece = 4 + 1024 * 1024 + 16  # length + one sealed megabyte
    header = 16

    # Cut after the first whole piece: what is left decrypts piece by piece,
    # so only the "this is the last" mark gives the cut away.
    with pytest.raises(DecryptionError):
        decrypt_bytes(sealed[: header + piece], KEY, "backup-1")
    with pytest.raises(DecryptionError):
        decrypt_bytes(sealed[:-5], KEY, "backup-1")
    # The second piece taken out.
    with pytest.raises(DecryptionError):
        decrypt_bytes(sealed[: header + piece] + sealed[header + 2 * piece :], KEY, "backup-1")


def test_a_file_is_encrypted_and_decrypted_on_disk(tmp_path):
    plain, sealed, back = tmp_path / "a.dump", tmp_path / "a.enc", tmp_path / "b.dump"
    plain.write_bytes(b"dump " * 500_000)

    encrypt_file(plain, sealed, KEY, "a.enc")
    decrypt_file(sealed, back, KEY, "a.enc")

    assert back.read_bytes() == plain.read_bytes()
    assert b"dump dump" not in sealed.read_bytes()


# ---- The storage ----


class _FakeS3:
    """Answers the calls S3Storage makes, from memory."""

    class _Missing(Exception):
        response = {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}}

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.broken = False

    def _fail(self) -> None:
        if self.broken:
            raise RuntimeError("connection refused")

    def put_object(self, Bucket, Key, Body):
        self._fail()
        self.objects[(Bucket, Key)] = bytes(Body)

    def upload_file(self, Filename, Bucket, Key):
        self._fail()
        self.objects[(Bucket, Key)] = Path(Filename).read_bytes()

    def _read(self, Bucket, Key) -> bytes:
        self._fail()
        if (Bucket, Key) not in self.objects:
            raise self._Missing()
        return self.objects[(Bucket, Key)]

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self._read(Bucket, Key))}

    def download_file(self, Bucket, Key, Filename):
        Path(Filename).write_bytes(self._read(Bucket, Key))

    def head_object(self, Bucket, Key):
        data = self._read(Bucket, Key)
        return {"ContentLength": len(data), "LastModified": datetime.fromtimestamp(NOW, timezone.utc)}

    def delete_object(self, Bucket, Key):
        self._fail()
        self.objects.pop((Bucket, Key), None)

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        client = self

        class _Pages:
            def paginate(self, Bucket, Prefix):
                client._fail()
                found = [
                    {"Key": key, "Size": len(data), "LastModified": datetime.fromtimestamp(NOW, timezone.utc)}
                    for (bucket, key), data in sorted(client.objects.items())
                    if bucket == Bucket and key.startswith(Prefix)
                ]
                # Two pages, as a large bucket gives.
                return [{"Contents": found[:1]}, {"Contents": found[1:]}] if found else [{}]

        return _Pages()


@pytest.fixture(params=["folder", "s3", "s3-with-prefix"])
def storage(request, tmp_path):
    if request.param == "folder":
        return LocalFolderStorage(tmp_path / "archive")
    return S3Storage(_FakeS3(), "calls", prefix="prod/site-1" if "prefix" in request.param else "")


def test_what_is_put_is_read_back_listed_and_removed(storage, tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"from a file")

    storage.put("transcripts/2026/10/a.json.enc", b"from memory")
    storage.put_file("recordings/2026/10/a.wav.enc", source)
    storage.put("recordings/2026/11/b.wav.enc", b"later")

    assert storage.get("transcripts/2026/10/a.json.enc") == b"from memory"
    assert storage.get("recordings/2026/10/a.wav.enc") == b"from a file"
    target = tmp_path / "back.bin"
    assert storage.get_file("recordings/2026/10/a.wav.enc", target) is True
    assert target.read_bytes() == b"from a file"
    assert storage.stat("recordings/2026/11/b.wav.enc").size_bytes == 5
    assert [o.key for o in storage.list("recordings/")] == [
        "recordings/2026/10/a.wav.enc",
        "recordings/2026/11/b.wav.enc",
    ]
    assert [o.size_bytes for o in storage.list("transcripts/")] == [11]

    storage.delete("recordings/2026/10/a.wav.enc")
    storage.delete("recordings/2026/10/a.wav.enc")  # already gone: not an error
    assert [o.key for o in storage.list("recordings/")] == ["recordings/2026/11/b.wav.enc"]


def test_what_is_not_there_is_none_not_an_error(storage, tmp_path):
    assert storage.get("recordings/none.enc") is None
    assert storage.stat("recordings/none.enc") is None
    assert storage.get_file("recordings/none.enc", tmp_path / "x") is False
    assert storage.list("recordings/") == ()


def test_putting_again_replaces(storage):
    storage.put("a/b", b"one")
    storage.put("a/b", b"two!")

    assert storage.get("a/b") == b"two!"
    assert storage.stat("a/b").size_bytes == 4


@pytest.mark.parametrize("key", ["", "/etc/passwd", "../outside", "a/../../b"])
def test_a_key_cannot_reach_outside_the_storage(storage, key):
    with pytest.raises(StorageError):
        storage.put(key, b"x")


def test_a_bucket_prefix_keeps_everything_under_it():
    client = _FakeS3()
    S3Storage(client, "calls", prefix="/prod/site-1/").put("backups/a.enc", b"x")

    assert list(client.objects) == [("calls", "prod/site-1/backups/a.enc")]


def test_a_storage_that_cannot_be_reached_raises_and_says_what_failed():
    client = _FakeS3()
    client.broken = True
    storage = S3Storage(client, "calls")

    for call in (
        lambda: storage.put("a", b"x"),
        lambda: storage.get("a"),
        lambda: storage.stat("a"),
        lambda: storage.delete("a"),
        lambda: storage.list(""),
    ):
        with pytest.raises(StorageError, match="connection refused"):
            call()


def test_the_storage_comes_from_the_settings(tmp_path):
    def build(**settings):
        return build_object_storage(Settings(_env_file=None, **settings))  # type: ignore[call-arg]

    assert build() is None
    assert build(archive_storage_provider="none") is None
    folder = build(archive_storage_provider="local", archive_storage_local_dir=str(tmp_path))
    assert folder.describe() == f"folder {tmp_path}"
    bucket = build(
        archive_storage_provider="s3",
        archive_s3_bucket="calls-archive",
        archive_s3_endpoint_url="https://s3.example.com",
        archive_s3_region="auto",
        archive_s3_access_key_id="id",
        archive_s3_secret_access_key="secret",
        archive_key_prefix="site-1",
    )
    assert bucket.describe() == "S3 bucket calls-archive under site-1/"
    with pytest.raises(StorageNotConfiguredError, match="ARCHIVE_S3_BUCKET, ARCHIVE_S3_ACCESS_KEY_ID"):
        build(archive_storage_provider="s3", archive_s3_secret_access_key="secret")
    with pytest.raises(StorageNotConfiguredError, match="use none, local or s3"):
        build(archive_storage_provider="azure")


# ---- Copies off the server ----


def _samples(count: int) -> bytes:
    return b"".join((n % 200).to_bytes(2, "little", signed=True) for n in range(count))


def _call_recording() -> CallRecording:
    recording = CallRecording(sample_rate=8000, max_seconds=3600)
    recording.append("inbound", _samples(4000))
    return recording


def _finished_call(call_id: str, ended_at: float, text: str = "The brakes still squeal.") -> Conversation:
    call = Conversation(call_id, start_time=ended_at - 60)
    call.add_utterance(Utterance(f"{call_id}-u1", text, SpeakerRole.CUSTOMER, ("en",), 0.0, 2.0))
    call.complete(ended_at)
    return call


class _World:
    """Recordings on disk, calls, a storage and the services over them."""

    def __init__(self, tmp_path, request, kind: str) -> None:
        self.clock = _Clock()
        self.storage = LocalFolderStorage(tmp_path / "offsite")
        self.live_state = InMemoryLiveStateStore()
        if kind == "sql":
            factory = _session_factory(request)
            self.calls = PostgresConversationRepository(factory)
            self.recording_repository = PostgresRecordingRepository(factory)
            self.transcripts = PostgresTranscriptArchiveRepository(factory)
        else:
            self.calls = InMemoryConversationRepository()
            self.recording_repository = InMemoryRecordingRepository()
            self.transcripts = InMemoryTranscriptArchiveRepository(
                lambda: self.calls.list_page(1000, 0)
            )
        self.recordings = RecordingArchive(
            self.recording_repository, tmp_path / "recordings", KEY, retention_days=90, clock=self.clock
        )
        self.offsite = OffsiteArchive(
            self.storage,
            KEY,
            self.transcripts,
            self.calls.get,
            lambda call_id: None,
            self.live_state,
            recordings=self.recordings,
            recording_repository=self.recording_repository,
            transcript_delay_seconds=900,
            clock=self.clock,
        )
        self.checker = RecordingIntegrityChecker(
            self.recordings,
            self.recording_repository,
            self.live_state,
            storage=self.storage,
            recheck_seconds=DAY,
            clock=self.clock,
        )

    def record(self, call_id: str):
        return self.recordings.save(call_id, _call_recording())

    def finish(self, call_id: str, ago: float = 3600.0) -> None:
        self.calls.add(_finished_call(call_id, self.clock.now - ago))

    def stored(self, call_id: str):
        return self.recording_repository.get(call_id)

    def local_file(self, call_id: str) -> Path:
        return self.recordings.path_of(self.stored(call_id))


@pytest.fixture(params=["memory", "sql"])
def world(request, tmp_path) -> _World:
    return _World(tmp_path, request, request.param)


def test_a_recording_notes_its_checksum_when_it_is_written(world):
    stored = world.record("call-1")

    assert stored.sha256 == sha256_of(world.local_file("call-1").read_bytes())
    assert (stored.archived_at, stored.verified_at, stored.integrity) == (None, None, None)


def test_a_recording_is_copied_as_it_is_stored_still_encrypted(world):
    world.record("call-1")

    run = world.offsite.run()

    stored = world.stored("call-1")
    assert (run.recordings_copied, run.failed) == (1, 0)
    assert stored.archive_key == "recordings/2026/10/call-1.wav.enc"
    assert stored.archived_at == NOW
    copy = world.storage.get(stored.archive_key)
    assert copy == world.local_file("call-1").read_bytes()
    assert not copy.startswith(b"RIFF")  # not a WAV anyone can play
    # Nothing is copied twice.
    assert world.offsite.run().recordings_copied == 0


def test_a_finished_calls_transcript_is_copied_encrypted_once_it_has_settled(world):
    world.finish("call-old", ago=3600)
    world.finish("call-just-ended", ago=60)

    run = world.offsite.run()

    assert run.transcripts_copied == 1
    copy = world.transcripts.get("call-old")
    assert copy.archive_key == "transcripts/2026/10/call-old.json.enc"
    sealed = world.storage.get(copy.archive_key)
    assert (copy.sha256, copy.size_bytes, copy.archived_at) == (sha256_of(sealed), len(sealed), NOW)
    assert b"brakes" not in sealed
    document = json.loads(decrypt_bytes(sealed, KEY, "call-old"))
    assert document["call_id"] == "call-old"
    assert document["utterances"][0]["transcript"] == "The brakes still squeal."
    assert document["utterances"][0]["speaker_role"] == "CUSTOMER"
    assert world.transcripts.get("call-just-ended") is None
    assert (world.offsite.transcript_counts().archived, world.offsite.transcript_counts().pending) == (1, 0)

    # A quarter of an hour on, the other has settled too.
    world.clock.now += 900
    assert world.offsite.run().transcripts_copied == 1
    assert world.transcripts.get("call-just-ended") is not None


def test_a_transcript_cannot_be_read_with_another_key_or_as_another_call(world):
    world.finish("call-1")
    world.offsite.run()
    sealed = world.storage.get(world.transcripts.get("call-1").archive_key)

    with pytest.raises(DecryptionError):
        decrypt_bytes(sealed, OTHER_KEY, "call-1")
    with pytest.raises(DecryptionError):
        decrypt_bytes(sealed, KEY, "call-2")


def test_a_call_in_progress_is_not_copied(world):
    world.calls.add(Conversation("live", start_time=NOW - 7200))

    assert world.offsite.run().transcripts_copied == 0
    assert world.offsite.transcript_counts().pending == 0


def test_a_copy_that_fails_is_counted_and_made_at_the_next_sweep(world, monkeypatch):
    world.record("call-1")
    world.finish("call-1")
    put, put_file = world.storage.put, world.storage.put_file

    def refuse(*args):
        raise StorageError("bucket unreachable")

    monkeypatch.setattr(world.storage, "put", refuse)
    monkeypatch.setattr(world.storage, "put_file", refuse)
    failed = world.offsite.run()

    assert (failed.recordings_copied, failed.transcripts_copied, failed.failed) == (0, 0, 2)
    assert "bucket unreachable" in failed.last_error
    assert world.stored("call-1").archived_at is None
    assert world.offsite.last_run == failed

    monkeypatch.setattr(world.storage, "put", put)
    monkeypatch.setattr(world.storage, "put_file", put_file)
    again = world.offsite.run()
    assert (again.recordings_copied, again.transcripts_copied, again.failed) == (1, 1, 0)


def test_a_recording_that_is_no_longer_what_was_written_is_not_copied(world):
    world.record("call-1")
    world.local_file("call-1").write_bytes(b"something else")

    run = world.offsite.run()

    assert (run.recordings_copied, world.stored("call-1").archived_at) == (0, None)
    assert world.storage.list("recordings/") == ()


def test_when_retention_removes_a_recording_its_copy_goes_too(world):
    world.record("call-1")
    world.offsite.run()
    key = world.stored("call-1").archive_key
    assert world.storage.stat(key) is not None

    world.clock.now += 91 * DAY
    assert world.recordings.purge_expired() == 1
    run = world.offsite.run()

    assert run.copies_removed == 1
    assert world.storage.stat(key) is None
    assert world.stored("call-1").archive_key is None
    assert world.offsite.run().copies_removed == 0


def test_a_call_has_its_copy_once_everything_kept_of_it_is_off_the_server(world):
    world.finish("with-recording")
    world.finish("without-recording")
    world.record("with-recording")
    assert not world.offsite.has_copy("with-recording")

    world.offsite.run()

    assert world.offsite.has_copy("with-recording")
    assert world.offsite.has_copy("without-recording")
    assert not world.offsite.has_copy("unknown")


def test_only_one_instance_copies_at_a_time(world):
    world.record("call-1")
    token = world.live_state.acquire_lock("offsite_archive", 60)

    skipped = world.offsite.run()

    assert skipped.skipped_reason == "Another instance is already running it."
    assert skipped.recordings_copied == 0
    world.live_state.release_lock("offsite_archive", token)
    assert world.offsite.run().recordings_copied == 1


def test_copies_are_filed_by_the_month_of_the_call():
    january = datetime(2027, 1, 31, 23, 59, tzinfo=timezone.utc).timestamp()

    assert object_key("recordings", january, "call 1/x.wav.enc") == "recordings/2027/01/call_1_x.wav.enc"


# ---- The recording check ----


def test_an_untouched_recording_checks_out(world):
    world.record("call-1")
    world.offsite.run()

    run = world.checker.run()

    stored = world.stored("call-1")
    assert (run.checked, run.ok, run.repaired, run.lost) == (1, 1, 0, 0)
    assert (stored.integrity, stored.verified_at) == (RecordingIntegrity.OK, NOW)
    assert world.checker.last_run == run


@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_a_damaged_or_missing_file_is_restored_from_its_copy(world, damage):
    world.record("call-1")
    world.offsite.run()
    path = world.local_file("call-1")
    original = path.read_bytes()
    if damage == "changed":
        path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    else:
        path.unlink()

    run = world.checker.run()

    assert (run.repaired, run.lost) == (1, 0)
    assert path.read_bytes() == original
    assert world.stored("call-1").integrity is RecordingIntegrity.REPAIRED
    # And it can be listened to again.
    assert world.recordings.read("call-1", "sup-1").startswith(b"RIFF")
    assert list(path.parent.glob("*.restore")) == []


def test_a_damaged_file_with_no_copy_is_lost_and_said_so(world, caplog):
    world.record("call-1")
    world.local_file("call-1").write_bytes(b"overwritten")

    run = world.checker.run()

    assert (run.lost, world.stored("call-1").integrity) == (1, RecordingIntegrity.LOST)
    assert [r.call_id for r in world.recording_repository.list_lost(10)] == ["call-1"]
    assert "missing or changed and cannot be restored" in caplog.text
    assert world.local_file("call-1").read_bytes() == b"overwritten"  # nothing was guessed


def test_a_damaged_copy_does_not_replace_the_file(world):
    world.record("call-1")
    world.offsite.run()
    world.local_file("call-1").unlink()
    world.storage.put(world.stored("call-1").archive_key, b"the copy is damaged as well")

    run = world.checker.run()

    assert run.lost == 1
    assert not world.local_file("call-1").exists()


def test_a_missing_copy_is_sent_again(world):
    world.record("call-1")
    world.offsite.run()
    key = world.stored("call-1").archive_key
    world.storage.delete(key)

    run = world.checker.run()

    assert run.repaired == 1
    assert world.stored("call-1").archived_at is None
    assert world.offsite.run().recordings_copied == 1
    assert world.storage.get(key) == world.local_file("call-1").read_bytes()


def test_a_recording_from_before_checksums_gets_one_at_its_first_check(world):
    stored = world.record("call-1")
    from dataclasses import replace

    world.recording_repository.save(replace(stored, sha256=None))

    world.checker.run()

    checked = world.stored("call-1")
    assert checked.sha256 == stored.sha256
    assert checked.integrity is RecordingIntegrity.OK


def test_a_checked_recording_is_left_alone_until_it_is_due_again(world):
    world.record("call-1")
    assert world.checker.run().checked == 1

    world.clock.now += 3600
    world.record("call-2")
    assert world.checker.run().checked == 1  # only the new one
    assert world.checker.run().checked == 0

    world.clock.now += DAY + 1
    assert world.checker.run().checked == 2
    # Asked for by hand: everything, whenever it was checked.
    assert world.checker.run(everything=True).checked == 2


def test_a_removed_recording_is_not_checked(world):
    world.record("call-1")
    world.clock.now += 91 * DAY
    world.recordings.purge_expired()

    assert world.checker.run().checked == 0


def test_a_storage_that_cannot_be_reached_is_not_a_verdict_on_the_file(world, monkeypatch):
    world.record("call-1")
    world.offsite.run()

    def refuse(key):
        raise StorageError("bucket unreachable")

    monkeypatch.setattr(world.storage, "stat", refuse)
    run = world.checker.run()

    assert (run.lost, run.repaired) == (0, 0)
    assert world.stored("call-1").verified_at is None  # checked again next time


def test_without_a_storage_the_files_are_still_checked(world):
    checker = RecordingIntegrityChecker(
        world.recordings, world.recording_repository, world.live_state, clock=world.clock
    )
    world.record("good")
    world.record("bad")
    world.local_file("bad").unlink()

    run = checker.run()

    assert (run.ok, run.lost) == (1, 1)


def test_the_counts_say_how_many_are_kept_copied_checked_and_lost(world):
    for call_id in ("a", "b", "c"):
        world.record(call_id)
    world.offsite.run()
    world.record("d")
    world.local_file("d").unlink()
    world.checker.run()

    counts = world.recording_repository.counts()

    assert (counts.kept, counts.archived, counts.checked, counts.lost) == (4, 3, 4, 1)


# ---- Database backups ----


class _Backups:
    def __init__(self, tmp_path, repository=None, days: float = 14.0) -> None:
        self.clock = _Clock()
        self.storage = LocalFolderStorage(tmp_path / "offsite")
        self.live_state = InMemoryLiveStateStore()
        self.repository = repository or InMemoryBackupRepository()
        self.dumps = 0
        self.fail: str | None = None
        self.service = DatabaseBackupService(
            self.storage,
            KEY,
            self.repository,
            self._dump,
            self.live_state,
            interval_seconds=DAY,
            retention_days=days,
            database_name="calls",
            clock=self.clock,
        )

    def _dump(self, target: Path) -> None:
        if self.fail:
            raise BackupError(self.fail)
        self.dumps += 1
        target.write_bytes(f"PGDMP dump number {self.dumps} ".encode() * 1000)


@pytest.fixture(params=["memory", "sql"])
def backups(request, tmp_path) -> _Backups:
    repository = None
    if request.param == "sql":
        repository = PostgresBackupRepository(_session_factory(request))
    return _Backups(tmp_path, repository)


def test_a_backup_is_dumped_encrypted_stored_and_recorded(backups):
    backup = backups.service.run()

    assert backup.status is BackupStatus.DONE
    assert backup.archive_key == "backups/20261011T100000Z-calls.dump.enc"
    assert (backup.started_at, backup.finished_at, backup.error) == (NOW, NOW, None)
    sealed = backups.storage.get(backup.archive_key)
    assert (backup.size_bytes, backup.sha256) == (len(sealed), sha256_of(sealed))
    assert b"PGDMP" not in sealed
    assert decrypt_bytes(sealed, KEY, "20261011T100000Z-calls.dump.enc").startswith(b"PGDMP dump number 1")
    assert backups.service.recent() == (backup,)
    assert backups.service.latest_done() == backup


def test_a_failed_backup_is_recorded_with_the_reason_and_stores_nothing(backups):
    backups.fail = "pg_dump failed: connection refused"

    backup = backups.service.run()

    assert (backup.status, backup.archive_key) == (BackupStatus.FAILED, None)
    assert backup.error == "pg_dump failed: connection refused"
    assert backups.storage.list("backups/") == ()
    assert backups.service.latest_done() is None


def test_a_backup_is_made_when_one_is_due_and_not_before(backups):
    assert backups.service.run_if_due().status is BackupStatus.DONE

    backups.clock.now += 3600
    assert backups.service.run_if_due() is None
    backups.clock.now += DAY
    assert backups.service.run_if_due().status is BackupStatus.DONE
    assert backups.dumps == 2


def test_a_failed_backup_is_tried_again_at_the_next_look(backups):
    backups.fail = "disk full"
    assert backups.service.run_if_due().status is BackupStatus.FAILED

    backups.fail = None
    backups.clock.now += 3600
    assert backups.service.run_if_due().status is BackupStatus.DONE


def test_old_backups_are_removed_but_never_the_newest_good_one(backups):
    first = backups.service.run()
    backups.clock.now += 10 * DAY
    second = backups.service.run()
    backups.clock.now += 5 * DAY  # the first is 15 days old, the second 5

    assert backups.service.purge_expired() == 1

    assert backups.storage.stat(first.archive_key) is None
    assert backups.storage.stat(second.archive_key) is not None
    kept, removed = backups.service.recent()
    assert (kept.removed_at, removed.removed_at) == (None, backups.clock.now)

    # Backups stop working for a month: the last good one is still there.
    backups.fail = "pg_dump is not installed"
    backups.clock.now += 30 * DAY
    backups.service.run_if_due()
    assert backups.storage.stat(second.archive_key) is not None


def test_only_one_instance_backs_up_at_a_time(backups):
    token = backups.live_state.acquire_lock("database_backup", 60)

    assert backups.service.run() is None
    assert backups.dumps == 0
    backups.live_state.release_lock("database_backup", token)
    assert backups.service.run().status is BackupStatus.DONE


def test_the_password_goes_to_pg_dump_in_the_environment_not_the_command():
    command, environment, name = pg_dump_command(
        "postgresql+psycopg://calls:s3cr3t-pw@db.internal:6543/call_data", "/usr/bin/pg_dump"
    )

    assert command == [
        "/usr/bin/pg_dump", "--format=custom", "--no-owner", "--no-privileges",
        "--host", "db.internal", "--port", "6543", "--username", "calls", "--dbname", "call_data",
    ]
    assert environment == {"PGPASSWORD": "s3cr3t-pw"}
    assert name == "call_data"
    assert "s3cr3t-pw" not in " ".join(command)
    with pytest.raises(BackupError):
        pg_dump_command("sqlite:///calls.db")


def test_a_missing_pg_dump_says_what_to_set(tmp_path):
    dump = pg_dump_to("postgresql://u:p@localhost/db", "/no/such/pg_dump")

    with pytest.raises(BackupError, match="BACKUP_PG_DUMP_PATH"):
        dump(tmp_path / "out.dump")


def test_a_backup_is_fetched_and_decrypted_for_restoring(backups, tmp_path):
    backups.service.run()
    backups.clock.now += DAY
    newest = backups.service.run()
    out = tmp_path / "restore.dump"

    restore_backup.restore(backups.storage, KEY, newest.archive_key, out)

    assert out.read_bytes().startswith(b"PGDMP dump number 2")
    with pytest.raises(DecryptionError):
        restore_backup.restore(backups.storage, OTHER_KEY, newest.archive_key, out)
    with pytest.raises(StorageError):
        restore_backup.restore(backups.storage, KEY, "backups/none.dump.enc", out)


def test_the_restore_command_lists_and_fetches_from_the_configured_storage(
    backups, tmp_path, monkeypatch, capsys
):
    backup = backups.service.run()
    import base64

    monkeypatch.setattr(
        restore_backup,
        "get_settings",
        lambda: Settings(  # type: ignore[call-arg]
            _env_file=None,
            archive_storage_provider="local",
            archive_storage_local_dir=str(tmp_path / "offsite"),
            archive_encryption_key=base64.urlsafe_b64encode(KEY).decode(),
        ),
    )
    out = tmp_path / "restore.dump"

    assert restore_backup.main(["--list"]) == 0
    assert backup.archive_key in capsys.readouterr().out
    assert restore_backup.main(["--latest", "--out", str(out)]) == 0
    assert out.read_bytes().startswith(b"PGDMP")
    assert restore_backup.main(["--key", "backups/none.enc", "--out", str(out)]) == 1


# ---- In the application ----


class _NoComplaints(ComplaintDetectionProvider):
    def detect(self, conversation, learning_context=()):
        return []


class _Calm(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEUTRAL, 0.7, "Calm.")


class _NoQuestions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


def _services(**settings):
    return build_api_services(
        _NoComplaints(), _Calm(), _NoQuestions(), Settings(_env_file=None, **settings)  # type: ignore[call-arg]
    )


def _on(tmp_path, **more) -> dict:
    return {
        "recording_enabled": True,
        "recording_dir": str(tmp_path / "recordings"),
        "recording_encryption_key": generate_key(),
        "archive_storage_provider": "local",
        "archive_storage_local_dir": str(tmp_path / "offsite"),
        "archive_encryption_key": generate_key(),
        "archive_transcript_delay_seconds": 0,
        **more,
    }


def _jobs(services) -> dict[str, float]:
    return {job.name: job.interval_seconds for job in services.background_jobs._jobs}


def test_nothing_leaves_the_server_unless_asked_for():
    services = _services()

    assert services.data_safety.storage is None
    assert services.data_safety.offsite is None
    assert services.data_safety.backups is None
    assert not {"offsite_archive", "recording_integrity", "database_backup"} & set(_jobs(services))


def test_turned_on_the_copies_the_check_and_the_backups_run_as_jobs(tmp_path):
    services = _services(
        **_on(tmp_path, backup_enabled=True, database_url="postgresql://u:p@localhost/calls")
    )

    jobs = _jobs(services)
    assert (jobs["offsite_archive"], jobs["recording_integrity"], jobs["database_backup"]) == (
        300.0, 3600.0, 3600.0,
    )
    assert services.data_safety.backups.retention_days == 14


def test_recordings_are_checked_even_when_nothing_is_copied(tmp_path):
    services = _services(
        recording_enabled=True,
        recording_dir=str(tmp_path / "recordings"),
        recording_encryption_key=generate_key(),
    )

    assert services.data_safety.integrity is not None
    assert "recording_integrity" in _jobs(services)
    assert "offsite_archive" not in _jobs(services)


def test_asked_for_without_a_key_nothing_is_copied_and_it_says_so(tmp_path, caplog):
    services = _services(
        archive_storage_provider="local", archive_storage_local_dir=str(tmp_path / "offsite")
    )

    assert services.data_safety.offsite is None
    assert "Copies off the server and backups are NOT running: ARCHIVE_ENCRYPTION_KEY is not set." in caplog.text
    assert not (tmp_path / "offsite").exists()


@pytest.mark.parametrize(
    ("settings", "problem"),
    [
        ({"archive_storage_provider": "local"}, "ARCHIVE_STORAGE_PROVIDER is local but ARCHIVE_ENCRYPTION_KEY is not set."),
        ({"archive_storage_provider": "azure"}, "ARCHIVE_STORAGE_PROVIDER must be none, local or s3."),
        ({"backup_enabled": True}, "BACKUP_ENABLED is true but ARCHIVE_STORAGE_PROVIDER does not say where backups go."),
        (
            {"archive_storage_provider": "s3", "archive_encryption_key": generate_key(),
             "archive_s3_bucket": "calls", "archive_s3_access_key_id": "replace-with-your-key"},
            "ARCHIVE_S3_ACCESS_KEY_ID must be set for S3 storage.",
        ),
        (
            {"archive_storage_provider": "local", "archive_encryption_key": generate_key(),
             "backup_enabled": True, "backup_retention_days": 0},
            "BACKUP_RETENTION_DAYS must be more than 0.",
        ),
    ],
)
def test_production_refuses_copies_that_could_not_run(settings, problem):
    assert problem in configuration_problems(Settings(_env_file=None, **settings))  # type: ignore[call-arg]


def test_production_accepts_copies_that_are_filled_in():
    problems = configuration_problems(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            archive_storage_provider="s3",
            archive_encryption_key=generate_key(),
            archive_s3_bucket="calls",
            archive_s3_access_key_id="id",
            archive_s3_secret_access_key="secret",
            backup_enabled=True,
        )
    )

    assert not [p for p in problems if "ARCHIVE" in p or "BACKUP" in p]


class _Api:
    def __init__(self, **settings) -> None:
        self.services = _services(**settings)
        self.client = TestClient(create_app(self.services))

    def user(self, user_id: str, role: UserRole) -> dict[str, str]:
        user = User(user_id, f"{user_id}@example.com", "hash", role, True, time.time())
        self.services.user_repository.save(user)
        return {"Authorization": f"Bearer {create_access_token(user)}"}

    def finished_call(self, call_id: str, headers) -> None:
        assert self.client.post("/api/v1/calls", json={"call_id": call_id, "start_time": None}, headers=headers).status_code == 201
        said = self.client.post(
            f"/api/v1/calls/{call_id}/utterances",
            json={"utterance_id": f"{call_id}-u1", "transcript": "The brakes still squeal.",
                  "speaker_role": "CUSTOMER", "languages": ["en"], "start_time": 0.0, "end_time": 2.0},
            headers=headers,
        )
        assert said.status_code == 200
        assert self.client.post(f"/api/v1/calls/{call_id}/complete", json={}, headers=headers).status_code == 200


URL = "/api/v1/admin/data-safety"


def test_an_administrator_sees_where_the_data_stands_and_can_copy_and_check_now(tmp_path):
    api = _Api(**_on(tmp_path))
    admin = api.user("admin-1", UserRole.ADMIN)
    api.finished_call("call-1", api.user("icr-1", UserRole.ICR))
    api.services.recording_archive.save("call-1", _call_recording())

    before = api.client.get(URL, headers=admin).json()
    assert before["archive_enabled"] is True
    assert before["storage"] == f"folder {tmp_path / 'offsite'}"
    assert (before["recordings_kept"], before["recordings_archived"]) == (1, 0)
    assert (before["transcripts_archived"], before["transcripts_pending"]) == (0, 1)
    assert (before["last_archive_run"], before["backups_enabled"]) == (None, False)
    analysis = api.client.get("/api/v1/calls/call-1/analysis", headers=admin).json()
    assert "archive_complete" not in analysis["logging_statuses"]

    copied = api.client.post(f"{URL}/copy", headers=admin).json()
    assert (copied["recordings_copied"], copied["transcripts_copied"], copied["failed"]) == (1, 1, 0)
    checked = api.client.post(f"{URL}/check", headers=admin).json()
    assert (checked["checked"], checked["ok"], checked["lost"]) == (1, 1, 0)

    after = api.client.get(URL, headers=admin).json()
    assert (after["recordings_archived"], after["recordings_checked"], after["recordings_lost"]) == (1, 1, 0)
    assert (after["transcripts_archived"], after["transcripts_pending"]) == (1, 0)
    assert after["last_archive_run"]["recordings_copied"] == 1
    assert after["last_integrity_run"]["ok"] == 1
    # "Archive complete" now means the copies are off the server.
    analysis = api.client.get("/api/v1/calls/call-1/analysis", headers=admin).json()
    assert "archive_complete" in analysis["logging_statuses"]
    # The recording itself is the supervisor's to open.
    supervisor = api.user("sup-1", UserRole.SUPERVISOR)
    recording = api.client.get("/api/v1/calls/call-1/recording", headers=supervisor).json()
    assert (recording["archived"], recording["integrity"]) == (True, "ok")
    assert recording["verified_at"] is not None


def test_a_lost_recording_is_listed_for_the_administrator(tmp_path):
    api = _Api(**_on(tmp_path))
    admin = api.user("admin-1", UserRole.ADMIN)
    api.finished_call("call-1", api.user("icr-1", UserRole.ICR))
    stored = api.services.recording_archive.save("call-1", _call_recording())
    api.services.recording_archive.path_of(stored).unlink()

    api.client.post(f"{URL}/check", headers=admin)

    body = api.client.get(URL, headers=admin).json()
    assert body["recordings_lost"] == 1
    assert [lost["call_id"] for lost in body["lost"]] == ["call-1"]
    supervisor = api.user("sup-1", UserRole.SUPERVISOR)
    recording = api.client.get("/api/v1/calls/call-1/recording", headers=supervisor).json()
    assert recording["integrity"] == "lost"


def test_with_everything_off_the_page_says_so_and_the_buttons_refuse():
    api = _Api()
    admin = api.user("admin-1", UserRole.ADMIN)

    body = api.client.get(URL, headers=admin).json()

    assert (body["archive_enabled"], body["recordings_enabled"], body["backups_enabled"]) == (
        False, False, False,
    )
    assert (body["storage"], body["backups"], body["lost"]) == (None, [], [])
    for action in ("copy", "check", "backup"):
        assert api.client.post(f"{URL}/{action}", headers=admin).status_code == 409


def test_a_backup_asked_for_by_hand_is_made_and_listed(tmp_path, monkeypatch):
    api = _Api(**_on(tmp_path, backup_enabled=True, database_url="postgresql://u:p@localhost/calls"))
    admin = api.user("admin-1", UserRole.ADMIN)
    monkeypatch.setattr(
        api.services.data_safety.backups, "_dump", lambda target: target.write_bytes(b"PGDMP test")
    )

    made = api.client.post(f"{URL}/backup", headers=admin)

    assert made.status_code == 200
    assert made.json()["status"] == "done"
    body = api.client.get(URL, headers=admin).json()
    assert body["backups_enabled"] is True
    assert (body["backup_interval_seconds"], body["backup_retention_days"]) == (86400, 14)
    assert [b["archive_key"] for b in body["backups"]] == [made.json()["archive_key"]]
    assert (tmp_path / "offsite" / made.json()["archive_key"]).is_file()


@pytest.mark.parametrize("role", [UserRole.ICR, UserRole.SUPERVISOR, UserRole.MANAGEMENT])
def test_only_administrators_see_or_run_any_of_it(role, tmp_path):
    api = _Api(**_on(tmp_path))
    headers = api.user("someone", role)

    assert api.client.get(URL, headers=headers).status_code == 403
    for action in ("copy", "check", "backup"):
        assert api.client.post(f"{URL}/{action}", headers=headers).status_code == 403
    assert api.client.get(URL).status_code == 401


def test_running_one_by_hand_is_in_the_audit_log(tmp_path):
    from app.services.audit_log import AuditFilter

    api = _Api(**_on(tmp_path))
    admin = api.user("admin-1", UserRole.ADMIN)

    api.client.post(f"{URL}/check", headers=admin)
    api.services.audit_log.flush()

    (entry,) = api.services.audit_log.search(AuditFilter()).entries
    assert (entry.action, entry.user_id, entry.status_code) == ("check_now", "admin-1", 200)
