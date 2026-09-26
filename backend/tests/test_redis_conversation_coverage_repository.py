import pytest

from app.composition import providers
from app.composition.providers import UnsupportedProviderError, create_coverage_repository
from app.core.config import Settings
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation_coverage import ConversationCoverage
from app.services.conversation_coverage_repository import ConversationCoverageRepository
from app.services.in_memory_conversation_coverage_repository import (
    InMemoryConversationCoverageRepository,
)
from app.services.redis_conversation_coverage_repository import (
    RedisConversationCoverageError,
    RedisConversationCoverageRepository,
)


class FakeRedisClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int | None]] = []

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex=None):
        self.store[key] = value
        self.set_calls.append((key, value, ex))
        return True

    def delete(self, key: str):
        return self.store.pop(key, None) is not None


def make_coverage(call_id: str = "call-1") -> ConversationCoverage:
    coverage = ConversationCoverage(call_id=call_id)
    coverage.add("Cost").detect()
    complaint = coverage.add("Hygiene")
    complaint.detect()
    complaint.probe()
    return coverage


def make_repository(*, client=None, **settings_overrides):
    client = client or FakeRedisClient()
    defaults = {
        "redis_ttl_seconds": 3600.0,
        "redis_key_prefix": "coverage",
    }
    defaults.update(settings_overrides)
    settings = Settings(_env_file=None, **defaults)  # type: ignore
    return RedisConversationCoverageRepository(settings, client=client), client


def test_is_conversation_coverage_repository():
    repository, _ = make_repository()
    assert isinstance(repository, ConversationCoverageRepository)


def test_save_and_get_round_trip():
    repository, _ = make_repository()

    repository.save(make_coverage())
    result = repository.get("call-1")

    assert result is not None
    assert result.call_id == "call-1"
    assert result.get("Cost").status is ComplaintCoverageStatus.DETECTED # type: ignore
    assert result.get("Hygiene").status is ComplaintCoverageStatus.PROBED # type: ignore


def test_get_missing_call_returns_none():
    repository, _ = make_repository()

    assert repository.get("unknown") is None


def test_calls_are_isolated_by_call_id():
    repository, _ = make_repository()
    repository.save(make_coverage("call-1"))
    repository.save(make_coverage("call-2"))

    assert repository.get("call-1").call_id == "call-1" # type: ignore
    assert repository.get("call-2").call_id == "call-2" # type: ignore


def test_key_uses_configured_prefix():
    repository, client = make_repository()

    repository.save(make_coverage())

    assert "coverage:call-1" in client.store


def test_ttl_is_passed_to_redis_set():
    repository, client = make_repository()

    repository.save(make_coverage())

    assert client.set_calls[0][2] == 3600


def test_zero_ttl_disables_expiry():
    repository, client = make_repository(redis_ttl_seconds=0.0)

    repository.save(make_coverage())

    assert client.set_calls[0][2] is None


def test_empty_coverage_round_trips():
    repository, _ = make_repository()
    repository.save(ConversationCoverage(call_id="call-empty"))

    result = repository.get("call-empty")

    assert result is not None
    assert result.complaints == ()


def test_corrupt_stored_value_raises_repository_error():
    repository, client = make_repository()
    client.store["coverage:call-bad"] = "not json"

    with pytest.raises(RedisConversationCoverageError):
        repository.get("call-bad")


def test_invalid_status_in_stored_value_raises_repository_error():
    repository, client = make_repository()
    client.store["coverage:call-bad"] = (
        '{"call_id": "call-bad", "complaints": '
        '[{"category": "Cost", "status": "not_a_status"}]}'
    )

    with pytest.raises(RedisConversationCoverageError):
        repository.get("call-bad")


def test_redis_errors_are_wrapped():
    class ExplodingClient(FakeRedisClient):
        def get(self, key: str):
            raise RuntimeError("connection reset")

    repository, _ = make_repository(client=ExplodingClient())

    with pytest.raises(RedisConversationCoverageError):
        repository.get("call-1")


def test_create_coverage_repository_defaults_to_in_memory():
    repository = create_coverage_repository(Settings(_env_file=None)) # type: ignore

    assert isinstance(repository, InMemoryConversationCoverageRepository)


def test_create_coverage_repository_selects_redis(monkeypatch):
    class RecordingRepository:
        def __init__(self, settings):
            self.settings = settings

    monkeypatch.setattr(providers, "RedisConversationCoverageRepository", RecordingRepository)

    repository = create_coverage_repository(
        Settings(_env_file=None, coverage_store_provider="redis") # type: ignore
    )

    assert isinstance(repository, RecordingRepository)


def test_create_coverage_repository_rejects_unknown_provider():
    with pytest.raises(UnsupportedProviderError, match="coverage store provider"):
        create_coverage_repository(Settings(_env_file=None, coverage_store_provider="bogus")) # type: ignore