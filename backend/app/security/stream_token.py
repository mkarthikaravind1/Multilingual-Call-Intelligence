"""Signed per-call tokens for the telephony media stream.

The answer webhook (itself signature-checked) puts a token in the stream URL
it hands the telephony provider; the stream endpoint accepts only a token
signed by us, for that call, and not yet expired. Without it anyone who can
reach the endpoint could inject audio into a live call.
"""

import time

import jwt

from app.core.config import Settings, get_settings

_ALGORITHM = "HS256"
_PURPOSE = "telephony_stream"


def create_stream_token(call_id: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    now = int(time.time())
    payload = {
        "sub": call_id,
        "purpose": _PURPOSE,
        "iat": now,
        "exp": now + settings.telephony_stream_token_ttl_seconds,
    }
    return jwt.encode(payload, settings.auth_secret_key, algorithm=_ALGORITHM)


def is_valid_stream_token(
    token: str | None, call_id: str, settings: Settings | None = None
) -> bool:
    if not token:
        return False
    settings = settings or get_settings()
    try:
        payload = jwt.decode(token, settings.auth_secret_key, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return False
    return payload.get("purpose") == _PURPOSE and payload.get("sub") == call_id
