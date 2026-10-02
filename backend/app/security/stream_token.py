"""Short-lived, purpose-bound tokens for WebSockets.

Telephony media stream: the answer webhook (itself signature-checked) puts a token in the stream URL
it hands the telephony provider; the stream endpoint accepts only a token
signed by us, for that call, and not yet expired. Without it anyone who can
reach the endpoint could inject audio into a live call.

Live-call view: the browser exchanges its access token (sent in the
Authorization header) for a ticket bound to the user and one call, valid
for a minute and usable once, and puts only that ticket in the WebSocket
URL. The long-lived access token never appears in a URL, where proxies and
logs would record it.

Every token here carries a "purpose" claim, and access tokens are refused
when they have one, so none of them can stand in for an access token.
"""

import time
import uuid
from dataclasses import dataclass

import jwt

from app.core.config import Settings, get_settings

_ALGORITHM = "HS256"
_PURPOSE = "telephony_stream"
_LIVE_CALL_PURPOSE = "live_call_ws"


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



@dataclass(frozen=True)
class LiveCallTicket:
    token: str
    expires_in: int


@dataclass(frozen=True)
class LiveCallTicketClaims:
    user_id: str
    call_id: str
    ticket_id: str
    expires_at: int


def create_live_call_ticket(
    user_id: str, call_id: str, settings: Settings | None = None
) -> LiveCallTicket:
    settings = settings or get_settings()
    now = int(time.time())
    ttl = max(1, settings.live_call_ws_token_ttl_seconds)
    payload = {
        "sub": user_id,
        "call_id": call_id,
        "purpose": _LIVE_CALL_PURPOSE,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + ttl,
    }
    return LiveCallTicket(
        token=jwt.encode(payload, settings.auth_secret_key, algorithm=_ALGORITHM),
        expires_in=ttl,
    )


def read_live_call_ticket(
    token: str | None, call_id: str, settings: Settings | None = None
) -> LiveCallTicketClaims | None:
    """The ticket's claims if it is ours, unexpired, for live-call viewing
    and for this call; otherwise None. Single use is enforced by the caller."""
    if not token:
        return None
    settings = settings or get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.auth_secret_key,
            algorithms=[_ALGORITHM],
            options={"require": ["exp", "sub", "jti"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("purpose") != _LIVE_CALL_PURPOSE or payload.get("call_id") != call_id:
        return None
    user_id, ticket_id = payload.get("sub"), payload.get("jti")
    if not isinstance(user_id, str) or not isinstance(ticket_id, str):
        return None
    return LiveCallTicketClaims(
        user_id=user_id, call_id=call_id, ticket_id=ticket_id, expires_at=int(payload["exp"])
    )
