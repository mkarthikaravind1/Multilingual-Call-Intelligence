"""State that every API instance must see the same way while calls are live:
which calls have an open media stream, each call's speaker roles, the latest
result of background jobs, and job locks. A single instance can keep it in
memory; several instances behind a load balancer need Redis."""

import json
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from typing import Any, Protocol


class LiveStateStore(ABC):
    @abstractmethod
    def get_json(self, key: str) -> Any | None:
        raise NotImplementedError

    def get_many_json(self, keys: Sequence[str]) -> list[Any | None]:
        """The value of each key, in order; None where there is none."""
        return [self.get_json(key) for key in keys]

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

    def renew_lock(self, name: str, token: str, ttl_seconds: float) -> bool:
        """Keep the lock for another ttl_seconds if token still holds it.
        False when it does not (it expired; someone else may have it)."""
        raise NotImplementedError

    @abstractmethod
    def release_lock(self, name: str, token: str) -> None:
        """Release the lock if token still holds it."""
        raise NotImplementedError

    def increment(self, key: str, ttl_seconds: float) -> int:
        """Add one to a counter and return the new count. A new counter
        expires ttl_seconds after its first increment. This default is not
        atomic; the stores below are."""
        count = int(self.get_json(key) or 0) + 1
        self.set_json(key, count, ttl_seconds=ttl_seconds if count == 1 else None)
        return count

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

    def increment(self, key: str, ttl_seconds: float) -> int:
        with self._lock:
            raw = self._live(key)
            if raw is None:
                count, expires = 1, self._clock() + ttl_seconds
            else:
                count, expires = int(json.loads(raw)) + 1, self._values[key][1]
            self._values[key] = (json.dumps(count), expires)
        return count

    def acquire_lock(self, name: str, ttl_seconds: float) -> str | None:
        token = f"{id(self)}-{time.time_ns()}"
        with self._lock:
            if self._live(_lock_key(name)) is not None:
                return None
            self._values[_lock_key(name)] = (token, self._clock() + ttl_seconds)
        return token

    def renew_lock(self, name: str, token: str, ttl_seconds: float) -> bool:
        with self._lock:
            if self._live(_lock_key(name)) != token:
                return False
            self._values[_lock_key(name)] = (token, self._clock() + ttl_seconds)
        return True

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


# Adds one; a new counter expires ARGV[1] seconds after it was started.
_INCREMENT_SCRIPT = (
    "local n = redis.call('incr', KEYS[1]) "
    "if n == 1 then redis.call('expire', KEYS[1], ARGV[1]) end "
    "return n"
)

# Deletes the lock only if it still holds our token (never someone else's).
_RELEASE_SCRIPT = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)


# Extends the lock only if it still holds our token.
_RENEW_SCRIPT = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
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

    def get_many_json(self, keys: Sequence[str]) -> list[Any | None]:
        # One round trip, where the client can (every real one).
        mget = getattr(self._client, "mget", None)
        if not keys or mget is None:
            return super().get_many_json(keys)
        values = []
        for raw in mget([self._key(key) for key in keys]):
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            values.append(None if raw is None else json.loads(raw))
        return values

    def set_json(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        self._client.set(self._key(key), json.dumps(value), ex=_seconds(ttl_seconds))

    def delete(self, key: str) -> None:
        self._client.delete(self._key(key))

    def increment(self, key: str, ttl_seconds: float) -> int:
        return int(
            self._client.eval(_INCREMENT_SCRIPT, 1, self._key(key), str(_seconds(ttl_seconds)))
        )

    def acquire_lock(self, name: str, ttl_seconds: float) -> str | None:
        token = f"{time.time_ns()}-{threading.get_ident()}"
        taken = self._client.set(
            self._key(_lock_key(name)), token, ex=_seconds(ttl_seconds), nx=True
        )
        return token if taken else None

    def renew_lock(self, name: str, token: str, ttl_seconds: float) -> bool:
        renewed = self._client.eval(
            _RENEW_SCRIPT, 1, self._key(_lock_key(name)), token, str(_seconds(ttl_seconds))
        )
        return bool(renewed)

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
