from typing import Protocol

import redis

from app.core.config import Settings, get_settings

_UNCONFIGURED = "not_configured"


class RedisClientError(Exception):
    pass


class RedisLike(Protocol):
    """Minimal surface this app needs from a Redis client, so repositories
    can be tested with a fake instead of a real connection."""

    def get(self, key: str) -> str | bytes | None: ...
    def set(self, key: str, value: str, ex: int | None = None) -> object: ...
    def delete(self, key: str) -> object: ...


def build_redis_client(settings: Settings | None = None) -> RedisLike:
    settings = settings or get_settings()
    url = settings.redis_url.strip()

    if not url or url == _UNCONFIGURED:
        raise RedisClientError("Redis URL is not configured.")

    return redis.Redis.from_url(
        url,
        socket_timeout=settings.redis_socket_timeout_seconds,
        decode_responses=True,
    )