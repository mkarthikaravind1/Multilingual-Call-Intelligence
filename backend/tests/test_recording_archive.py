"""Encrypted call recordings: what is written, that only the right key and
call read it back, retention, who may listen (and that it is logged), and
that recording is off unless asked for and never unencrypted."""

import io
import logging
import time
import wave

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentLabel, SentimentResult
from app.api.app_factory import create_app
from app.api.v1.telephony_ws import _archive_recording
from app.api.wiring import build_api_services
from app.core.config import Settings
from app.core.production_checks import configuration_problems
from app.domain.user import User, UserRole
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import build_session_factory
from app.infrastructure.database.repositories.recording_repository import (
    PostgresRecordingRepository,
)
from app.security.jwt import create_access_token
from app.services.call_recording_store import CallRecording
from app.services.recording_archive import (
    InMemoryRecordingRepository,
    RecordingArchive,
    RecordingError,
    RecordingNotFoundError,
    RecordingPlay,
    StoredRecording,
    generate_key,
    parse_key,
    to_wav,
)

DAY = 86400.0
KEY = parse_key(generate_key())


class _Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _samples(*values: int) -> bytes:
    return b"".join(value.to_bytes(2, "little", signed=True) for value in values)


def _recording(tracks: dict, rate: int = 8000) -> CallRecording:
    recording = CallRecording(sample_rate=rate, max_seconds=3600)
    for track, pcm in tracks.items():
        recording.append(track, pcm)
    return recording


def _archive(tmp_path, clock=None, key=KEY, repository=None, days=90.0) -> RecordingArchive:
    return RecordingArchive(
        repository or InMemoryRecordingRepository(),
        tmp_path / "recordings",
        key,
        retention_days=days,
        clock=clock or _Clock(),
    )


# ---- The key ----

def test_a_generated_key_is_thirty_two_bytes_and_each_one_differs():
    assert len(parse_key(generate_key())) == 32
    assert generate_key() != generate_key()


@pytest.mark.parametrize(
    ("value", "message"),
    [("", "is not set"), ("   ", "is not set"), ("not base64!!", "32 random bytes|valid base64"),
     ("c2hvcnQ=", "it holds 5")],
)
def test_a_missing_or_wrong_key_is_refused(value, message):
    with pytest.raises(RecordingError, match=message):
        parse_key(value)


# ---- The file ----

def test_a_mixed_stream_is_one_channel_and_two_sides_are_two():
    mono, channels = to_wav(_recording({None: _samples(1, 2, 3)}))
    assert channels == 1
    with wave.open(io.BytesIO(mono)) as wav:
        assert (wav.getnchannels(), wav.getframerate(), wav.getnframes()) == (1, 8000, 3)
        assert wav.readframes(3) == _samples(1, 2, 3)

    # The caller on the left; the shorter side is padded with silence.
    stereo, channels = to_wav(
        _recording({"outbound": _samples(10, 20, 30), "inbound": _samples(1, 2)}, rate=16000)
    )
    assert channels == 2
    with wave.open(io.BytesIO(stereo)) as wav:
        assert (wav.getnchannels(), wav.getframerate(), wav.getnframes()) == (2, 16000, 3)
        assert wav.readframes(3) == _samples(1, 10, 2, 20, 0, 30)


def test_a_recording_is_stored_encrypted_and_read_back_whole(tmp_path):
    clock = _Clock()
    archive = _archive(tmp_path, clock)
    audio = _samples(*range(-400, 400))

    stored = archive.save("plivo-abc", _recording({None: audio}))

    assert stored is not None
    assert (stored.duration_seconds, stored.channels, stored.sample_rate) == (0.1, 1, 8000)
    assert stored.delete_after == clock.now + 90 * DAY
    on_disk = (tmp_path / "recordings" / stored.file_name).read_bytes()
    assert stored.size_bytes == len(on_disk)
    # Neither the audio nor a WAV header is readable in the file.
    assert audio[:64] not in on_disk and b"RIFF" not in on_disk and b"WAVE" not in on_disk

    with wave.open(io.BytesIO(archive.read("plivo-abc", "sup"))) as wav:
        assert wav.readframes(wav.getnframes()) == audio
    assert not list((tmp_path / "recordings").glob("*.part"))


def test_the_same_audio_is_encrypted_differently_each_time(tmp_path):
    archive = _archive(tmp_path)
    a = archive.save("call-a", _recording({None: _samples(*range(100))}))
    b = archive.save("call-b", _recording({None: _samples(*range(100))}))

    folder = tmp_path / "recordings"
    assert (folder / a.file_name).read_bytes() != (folder / b.file_name).read_bytes()


def test_another_key_a_damaged_file_or_another_calls_file_cannot_be_read(tmp_path):
    repository = InMemoryRecordingRepository()
    archive = _archive(tmp_path, repository=repository)
    stored = archive.save("call-a", _recording({None: _samples(*range(100))}))
    archive.save("call-b", _recording({None: _samples(*range(50))}))
    folder = tmp_path / "recordings"

    other_key = _archive(tmp_path, key=parse_key(generate_key()), repository=repository)
    with pytest.raises(RecordingError, match="cannot be decrypted"):
        other_key.read("call-a", "sup")

    # call-b's file put in call-a's place: it was encrypted for call-b.
    path = folder / stored.file_name
    original = path.read_bytes()
    path.write_bytes((folder / "call-b.wav.enc").read_bytes())
    with pytest.raises(RecordingError, match="cannot be decrypted"):
        archive.read("call-a", "sup")

    damaged = bytearray(original)
    damaged[-1] ^= 0x01
    path.write_bytes(bytes(damaged))
    with pytest.raises(RecordingError, match="cannot be decrypted"):
        archive.read("call-a", "sup")

    # None of those counted as a listen.
    assert archive.plays("call-a") == ()
    path.write_bytes(original)
    assert archive.read("call-a", "sup")


def test_an_empty_recording_is_not_kept_and_the_first_of_a_call_wins(tmp_path):
    archive = _archive(tmp_path)

    assert archive.save("call-a", _recording({})) is None
    assert archive.save("call-a", _recording({None: b""})) is None
    assert archive.get("call-a") is None

    first = archive.save("call-a", _recording({None: _samples(1, 2, 3, 4)}))
    again = archive.save("call-a", _recording({None: _samples(9, 9)}))
    assert again is None
    with wave.open(io.BytesIO(archive.read("call-a", "sup"))) as wav:
        assert wav.getnframes() == 4
    assert archive.get("call-a") == first


def test_an_odd_call_id_cannot_write_outside_the_folder(tmp_path):
    archive = _archive(tmp_path)

    stored = archive.save("../../etc/passwd", _recording({None: _samples(1, 2)}))

    assert "/" not in stored.file_name and "\\" not in stored.file_name
    assert [p.name for p in (tmp_path / "recordings").iterdir()] == [stored.file_name]
    assert archive.read("../../etc/passwd", "sup")


def test_every_listen_is_logged_with_who_and_when(tmp_path):
    clock = _Clock(5_000.0)
    archive = _archive(tmp_path, clock)
    archive.save("call-a", _recording({None: _samples(1, 2)}))

    archive.read("call-a", "sup")
    clock.now = 6_000.0
    archive.read("call-a", "admin")

    assert archive.plays("call-a") == (
        RecordingPlay("call-a", "sup", 5_000.0),
        RecordingPlay("call-a", "admin", 6_000.0),
    )
    assert archive.plays("call-b") == ()


# ---- Retention ----

def test_a_recording_is_removed_once_its_days_are_up_and_not_before(tmp_path):
    clock = _Clock(1_000_000.0)
    archive = _archive(tmp_path, clock, days=30)
    old = archive.save("old", _recording({None: _samples(1, 2)}))
    clock.now += 10 * DAY
    new = archive.save("new", _recording({None: _samples(3, 4)}))
    folder = tmp_path / "recordings"

    clock.now = 1_000_000.0 + 30 * DAY - 1
    assert archive.purge_expired() == 0
    assert (folder / old.file_name).exists()

    clock.now += 1
    assert archive.purge_expired() == 1
    assert not (folder / old.file_name).exists()
    assert (folder / new.file_name).exists()
    gone = archive.get("old")
    assert (gone.is_available, gone.deleted_at) == (False, clock.now)
    with pytest.raises(RecordingNotFoundError):
        archive.read("old", "sup")
    assert archive.read("new", "sup")

    # Already removed: nothing more to do, and it is not kept again.
    assert archive.purge_expired() == 0
    assert archive.save("old", _recording({None: _samples(5, 6)})) is None


def test_a_file_already_missing_is_still_marked_as_removed(tmp_path):
    clock = _Clock()
    archive = _archive(tmp_path, clock, days=1)
    stored = archive.save("call-a", _recording({None: _samples(1, 2)}))
    (tmp_path / "recordings" / stored.file_name).unlink()

    with pytest.raises(RecordingNotFoundError, match="not on this server"):
        archive.read("call-a", "sup")
    clock.now += 2 * DAY
    assert archive.purge_expired() == 1
    assert archive.get("call-a").is_available is False


# ---- The database ----

def test_recordings_and_listens_are_stored_in_the_database():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    try:
        repository = PostgresRecordingRepository(build_session_factory(engine))
        kept = StoredRecording("a", "a.wav.enc", 12.5, 4096, 16000, 2, 100.0, 200.0)
        repository.save(kept)
        repository.save(StoredRecording("b", "b.wav.enc", 3.0, 512, 8000, 1, 100.0, 900.0))
        repository.save(StoredRecording("c", "c.wav.enc", 3.0, 512, 8000, 1, 50.0, 150.0, 160.0))

        assert repository.get("a") == kept
        assert repository.get("nope") is None
        # Due, and not already removed.
        assert [r.call_id for r in repository.list_expired(500.0)] == ["a"]
        assert repository.list_expired(199.0) == ()

        repository.add_play(RecordingPlay("a", "sup", 10.0))
        repository.add_play(RecordingPlay("a", "admin", 20.0))
        repository.add_play(RecordingPlay("b", "sup", 15.0))
        assert [p.user_id for p in repository.list_plays("a")] == ["sup", "admin"]
    finally:
        engine.dispose()


# ---- Off unless asked for, and never unencrypted ----

class _NoComplaints(ComplaintDetectionProvider):
    def detect(self, conversation, learning_context=()):
        return []


class _Neutral(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEUTRAL, 0.9, "Calm.")


class _NoQuestions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


def _services(**settings):
    return build_api_services(
        _NoComplaints(), _Neutral(), _NoQuestions(), Settings(_env_file=None, **settings)  # type: ignore[call-arg]
    )


def test_recordings_are_not_kept_unless_turned_on():
    services = _services()

    assert services.recording_archive is None
    assert "recording_retention" not in _running_jobs(services)


def _running_jobs(services) -> set[str]:
    """The background jobs that run (one with interval 0 does not)."""
    return {job.name for job in services.background_jobs._jobs}


def test_turned_on_without_a_usable_key_nothing_is_kept_and_it_says_so(caplog, tmp_path):
    with caplog.at_level(logging.ERROR):
        services = _services(recording_enabled=True, recording_dir=str(tmp_path))

    assert services.recording_archive is None
    assert "Call recordings will NOT be kept" in caplog.text
    assert not list(tmp_path.iterdir())


def test_production_refuses_to_start_with_recording_on_and_no_key():
    def problems(**settings):
        return [
            p
            for p in configuration_problems(Settings(_env_file=None, **settings))  # type: ignore[call-arg]
            if "RECORDING" in p
        ]

    assert problems() == []
    assert problems(recording_enabled=True) == [
        "RECORDING_ENABLED is true but RECORDING_ENCRYPTION_KEY is not set."
    ]
    assert problems(recording_enabled=True, recording_encryption_key=generate_key()) == []
    assert problems(
        recording_enabled=True, recording_encryption_key=generate_key(), recording_retention_days=0
    ) == ["RECORDING_RETENTION_DAYS must be more than 0."]


def test_a_failure_to_keep_a_recording_is_logged_and_does_not_reach_the_call(caplog):
    class _Broken:
        def save(self, call_id, recording):
            raise OSError("disk full")

    with caplog.at_level(logging.ERROR):
        _archive_recording(_Broken(), "call-a", _recording({None: _samples(1, 2)}))

    assert "Could not keep the recording of call 'call-a'" in caplog.text


# ---- The API ----

def _api(tmp_path):
    services = _services(
        recording_enabled=True,
        recording_dir=str(tmp_path / "recordings"),
        recording_encryption_key=generate_key(),
        recording_retention_days=30,
    )
    client = TestClient(create_app(services))

    def sign_in(user_id: str, role: UserRole) -> dict[str, str]:
        user = User(user_id, f"{user_id}@example.com", "hash", role, True, time.time())
        services.user_repository.save(user)
        return {"Authorization": f"Bearer {create_access_token(user)}"}

    return client, services, sign_in


def test_supervisors_and_admins_can_listen_and_executives_cannot(tmp_path):
    client, services, sign_in = _api(tmp_path)
    icr = sign_in("icr", UserRole.ICR)
    supervisor = sign_in("sup", UserRole.SUPERVISOR)
    client.post("/api/v1/calls", json={"call_id": "c1", "start_time": None}, headers=icr)
    client.post("/api/v1/calls", json={"call_id": "c2", "start_time": None}, headers=icr)
    services.recording_archive.save("c1", _recording({None: _samples(*range(8000))}))
    assert "recording_retention" in _running_jobs(services)

    info = client.get("/api/v1/calls/c1/recording", headers=supervisor).json()
    assert (info["enabled"], info["available"], info["duration_seconds"], info["channels"]) == (
        True,
        True,
        1.0,
        1,
    )
    assert info["delete_after"] - info["created_at"] == pytest.approx(30 * DAY)
    assert info["plays"] == 0

    audio = client.get("/api/v1/calls/c1/recording/audio", headers=supervisor)
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"
    assert audio.headers["cache-control"] == "no-store"
    with wave.open(io.BytesIO(audio.content)) as wav:
        assert wav.getnframes() == 8000
    admin = sign_in("adm", UserRole.ADMIN)
    assert client.get("/api/v1/calls/c1/recording/audio", headers=admin).status_code == 200

    # Both listens are on record.
    assert client.get("/api/v1/calls/c1/recording", headers=supervisor).json()["plays"] == 2
    assert [p.user_id for p in services.recording_archive.plays("c1")] == ["sup", "adm"]

    # A call without a recording (e.g. one started in the web app).
    none = client.get("/api/v1/calls/c2/recording", headers=supervisor).json()
    assert (none["enabled"], none["available"]) == (True, False)
    assert client.get("/api/v1/calls/c2/recording/audio", headers=supervisor).status_code == 404

    for path in ("/api/v1/calls/c1/recording", "/api/v1/calls/c1/recording/audio"):
        assert client.get(path, headers=icr).status_code == 403
        assert client.get(path).status_code == 401
    assert client.get("/api/v1/calls/nope/recording", headers=supervisor).status_code == 404
    assert len(services.recording_archive.plays("c1")) == 2


def test_with_recording_off_the_api_says_so():
    services = _services()
    client = TestClient(create_app(services))
    user = User("sup", "sup@example.com", "hash", UserRole.SUPERVISOR, True, time.time())
    services.user_repository.save(user)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    client.post("/api/v1/calls", json={"call_id": "c1", "start_time": None}, headers=headers)

    info = client.get("/api/v1/calls/c1/recording", headers=headers).json()

    assert (info["enabled"], info["available"]) == (False, False)
    assert client.get("/api/v1/calls/c1/recording/audio", headers=headers).status_code == 404
