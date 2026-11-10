from typing import Optional
from fastapi import Header, HTTPException, WebSocket, status
from app.config import get_settings


def verify_bearer_token(authorization: Optional[str] = Header(None)) -> bool:
    """Verifies HTTP Authorization header if SPEECH_SERVER_TOKEN is configured."""
    settings = get_settings()
    configured_token = settings.SPEECH_SERVER_TOKEN
    if not configured_token:
        return True

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header scheme. Expected 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1]
    if token != configured_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True


async def verify_websocket_auth(websocket: WebSocket) -> bool:
    """Verifies token for WebSocket connections via header or query parameter."""
    settings = get_settings()
    configured_token = settings.SPEECH_SERVER_TOKEN
    if not configured_token:
        return True

    # 1. Check HTTP header during handshake
    auth_header = websocket.headers.get("authorization")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1] == configured_token:
            return True

    # 2. Check query parameter: ?token=...
    query_token = websocket.query_params.get("token")
    if query_token and query_token == configured_token:
        return True

    # 3. Check Sec-WebSocket-Protocol (often used in browser environments)
    protocols = websocket.headers.get("sec-websocket-protocol", "").split(",")
    for p in protocols:
        if p.strip() == configured_token:
            return True

    return False

