from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.dependencies import get_user_repository
from app.domain.user import User, UserRole
from app.domain.user_repository import UserRepository
from app.security.jwt import TokenError, decode_access_token
from starlette.websockets import WebSocket

_bearer_scheme = HTTPBearer(auto_error=False)

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    user_repository: UserRepository = Depends(get_user_repository),
) -> User:
    if credentials is None:
        raise _CREDENTIALS_ERROR

    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError:
        raise _CREDENTIALS_ERROR

    user_id = payload.get("sub")
    if not isinstance(user_id, str):
        raise _CREDENTIALS_ERROR

    user = user_repository.get_by_id(user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_ERROR

    return user


def require_roles(*roles: UserRole):
    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return user

    return _check

def _decode_ws_token(websocket: WebSocket) -> User | None:
    token = websocket.query_params.get("token")
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except TokenError:
        return None

    user_id = payload.get("sub")
    if not isinstance(user_id, str):
        return None

    user_repository: UserRepository = websocket.app.state.services.user_repository
    user = user_repository.get_by_id(user_id)
    if user is None or not user.is_active:
        return None
    return user


def get_current_user_ws(websocket: WebSocket) -> User | None:
    """Authenticate a WebSocket via a `?token=` query param.

    Returns None instead of raising HTTPException — HTTPException doesn't
    translate to WS close frames, so the caller closes the socket itself
    with an appropriate code.
    """
    return _decode_ws_token(websocket)