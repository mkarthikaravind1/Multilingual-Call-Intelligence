import json

from app.core.config import Settings, get_settings
from app.domain.telephony_call_mapping import TelephonyCallMapping
from app.infrastructure.cache.redis_client import RedisLike, build_redis_client
from app.services.telephony_call_mapping_repository import TelephonyCallMappingRepository


class RedisTelephonyCallMappingError(Exception):
    pass


def _serialize(mapping: TelephonyCallMapping) -> str:
    return json.dumps(
        {
            "provider": mapping.provider,
            "provider_call_id": mapping.provider_call_id,
            "call_id": mapping.call_id,
            "created_at": mapping.created_at,
        }
    )


def _deserialize(raw: str | bytes) -> TelephonyCallMapping:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")

    data = json.loads(raw)

    return TelephonyCallMapping(
        provider=data["provider"],
        provider_call_id=data["provider_call_id"],
        call_id=data["call_id"],
        created_at=data["created_at"],
    )


class RedisTelephonyCallMappingRepository(TelephonyCallMappingRepository):
    def __init__(
        self, settings: Settings | None = None, client: RedisLike | None = None
    ) -> None:
        settings = settings or get_settings()
        self._ttl_seconds = settings.redis_ttl_seconds
        self._key_prefix = settings.call_mapping_key_prefix.strip() or "telephony_call_mapping"
        self._client = client or build_redis_client(settings)

    def save(self, mapping: TelephonyCallMapping) -> None:
        ttl = int(self._ttl_seconds) if self._ttl_seconds and self._ttl_seconds > 0 else None
        try:
            self._client.set(self._key(mapping.provider_call_id), _serialize(mapping), ex=ttl)
        except Exception as exc:
            raise RedisTelephonyCallMappingError(
                f"Redis save failed for provider_call_id {mapping.provider_call_id!r}."
            ) from exc

    def get_by_provider_call_id(self, provider_call_id: str) -> TelephonyCallMapping | None:
        try:
            raw = self._client.get(self._key(provider_call_id))
        except Exception as exc:
            raise RedisTelephonyCallMappingError(
                f"Redis get failed for provider_call_id {provider_call_id!r}."
            ) from exc
        if raw is None:
            return None
        try:
            return _deserialize(raw)
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            raise RedisTelephonyCallMappingError(
                f"Corrupt telephony call mapping for provider_call_id {provider_call_id!r}."
            ) from exc

    def _key(self, provider_call_id: str) -> str:
        return f"{self._key_prefix}:{provider_call_id}"