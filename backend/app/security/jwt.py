import time

import jwt

from app.core.config import Settings, get_settings
from app.domain.user import User

_ALGORITHM = "HS256"


class TokenError(Exception):
    pass


def create_access_token(user: User, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    now = int(time.time())
    payload = {
        "sub": user.user_id,
        "role": user.role.value,
        "iat": now,
        "exp": now + settings.auth_access_token_expire_minutes * 60,
    }
    return jwt.encode(payload, settings.auth_secret_key, algorithm=_ALGORITHM)


def decode_access_token(token: str, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    try:
        return jwt.decode(token, settings.auth_secret_key, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid or expired token.") from exc