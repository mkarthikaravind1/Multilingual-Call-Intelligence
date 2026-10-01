"""State that every API instance must see the same way while calls are live:
which calls have an open media stream, each call's speaker roles, the latest
result of background jobs, and job locks. A single instance can keep it in
memory; several instances behind a load balancer need Redis."""

import json
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Protocol


class LiveStateStore(ABC):
    @abstractmethod
    def get_json(self, key: str) -> Any | None:
        raise NotImplementedError

    @abstractmethod
    def set_json(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def acquire_lock(self, name: str, ttl_seconds: float) -> str | None:
        """Take the named lock unless someone holds it. Returns a token to
        release it with, or None. The lock expires after ttl_seconds, so a
        crashed holder never blocks others for good."""
        raise NotImplementedError

    @abstractmethod
    def release_lock(self, name: str, token: str) -> None:
        """Release the lock if token still holds it."""
        raise NotImplementedError

    def ping(self) -> None:
        """Raise if the store is unreachable."""


class InMemoryLiveStateStore(LiveStateStore):
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._values: dict[str, tuple[str, float | None]] = {}
        self._lock = threading.Lock()

    def get_json(self, key: str) -> Any | None:
        with self._lock:
            raw = self._live(key)
        return None if raw is None else json.loads(raw)

    def set_json(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        expires = None if not ttl_seconds else self._clock() + ttl_seconds
        with self._lock:
            self._values[key] = (json.dumps(value), expires)

    def delete(self, key: str) -> None:
        with self._lock:
            self._values.pop(key, None)

    def acquire_lock(self, name: str, ttl_seconds: float) -> str | None:
        token = f"{id(self)}-{time.time_ns()}"
        with self._lock:
            if self._live(_lock_key(name)) is not None:
                return None
            self._values[_lock_key(name)] = (token, self._clock() + ttl_seconds)
        return token

    def release_lock(self, name: str, token: str) -> None:
        with self._lock:
            if self._live(_lock_key(name)) == token:
                self._values.pop(_lock_key(name), None)

    def _live(self, key: str) -> str | None:
        entry = self._values.get(key)
        if entry is None:
            return None
        raw, expires = entry
        if expires is not None and expires <= self._clock():
            del self._values[key]
            return None
        return raw


class RedisClient(Protocol):
    def get(self, key: str) -> str | bytes | None: ...
    def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> object: ...
    def delete(self, key: str) -> object: ...
    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> object: ...
    def ping(self) -> object: ...


# Deletes the lock only if it still holds our token (never someone else's).
_RELEASE_SCRIPT = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)


class RedisLiveStateStore(LiveStateStore):
    def __init__(self, client: RedisClient, key_prefix: str = "live_state") -> None:
        self._client = client
        self._prefix = key_prefix.strip() or "live_state"

    def get_json(self, key: str) -> Any | None:
        raw = self._client.get(self._key(key))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    def set_json(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        self._client.set(self._key(key), json.dumps(value), ex=_seconds(ttl_seconds))

    def delete(self, key: str) -> None:
        self._client.delete(self._key(key))

    def acquire_lock(self, name: str, ttl_seconds: float) -> str | None:
        token = f"{time.time_ns()}-{threading.get_ident()}"
        taken = self._client.set(
            self._key(_lock_key(name)), token, ex=_seconds(ttl_seconds), nx=True
        )
        return token if taken else None

    def release_lock(self, name: str, token: str) -> None:
        self._client.eval(_RELEASE_SCRIPT, 1, self._key(_lock_key(name)), token)

    def ping(self) -> None:
        self._client.ping()

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"


def _lock_key(name: str) -> str:
    return f"lock:{name}"


def _seconds(ttl: float | None) -> int | None:
    return None if not ttl else max(1, int(ttl))
