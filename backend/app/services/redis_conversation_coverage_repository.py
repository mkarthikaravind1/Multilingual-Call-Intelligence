import json

from app.core.config import Settings, get_settings
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation_coverage import ConversationCoverage
from app.infrastructure.cache.redis_client import RedisLike, build_redis_client
from app.services.conversation_coverage_repository import ConversationCoverageRepository


class RedisConversationCoverageError(Exception):
    pass


def _serialize(coverage: ConversationCoverage) -> dict:
    return {
        "call_id": coverage.call_id,
        "complaints": [
            {"category": c.category, "status": c.status.value}
            for c in coverage.complaints
        ],
    }


def _deserialize(data: dict) -> ConversationCoverage:
    coverage = ConversationCoverage(call_id=data["call_id"])
    for item in data["complaints"]:
        complaint = coverage.add(item["category"])
        complaint.status = ComplaintCoverageStatus(item["status"])
    return coverage


class RedisConversationCoverageRepository(ConversationCoverageRepository):
    """Redis-backed ConversationCoverageRepository for distributed live-call
    state. Serializes only through ConversationCoverage/ComplaintCoverage's
    public API (add() + the public `status` field), so it stays decoupled
    from their internals."""

    def __init__(
        self, settings: Settings | None = None, client: RedisLike | None = None
    ) -> None:
        settings = settings or get_settings()
        self._ttl_seconds = settings.redis_ttl_seconds
        self._key_prefix = settings.redis_key_prefix.strip() or "conversation_coverage"
        self._client = client or build_redis_client(settings)

    def save(self, coverage: ConversationCoverage) -> None:
        if not isinstance(coverage, ConversationCoverage):
            raise TypeError("coverage must be a ConversationCoverage.")

        payload = json.dumps(_serialize(coverage))
        ttl = int(self._ttl_seconds) if self._ttl_seconds and self._ttl_seconds > 0 else None

        try:
            self._client.set(self._key(coverage.call_id), payload, ex=ttl)
        except Exception as exc:
            raise RedisConversationCoverageError(
                f"Redis save failed for call {coverage.call_id!r}."
            ) from exc

    def get(self, call_id: str) -> ConversationCoverage | None:
        try:
            raw = self._client.get(self._key(call_id))
        except Exception as exc:
            raise RedisConversationCoverageError(
                f"Redis get failed for call {call_id!r}."
            ) from exc

        if raw is None:
            return None

        try:
            return _deserialize(json.loads(raw))
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            raise RedisConversationCoverageError(
                f"Corrupt conversation coverage data for call {call_id!r}."
            ) from exc

    def _key(self, call_id: str) -> str:
        return f"{self._key_prefix}:{call_id}"