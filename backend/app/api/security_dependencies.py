import logging
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.dependencies import get_call_service, get_user_repository
from app.domain.conversation import ConversationStatus
from app.domain.user import CALL_TAKING_ROLES, User, UserRole
from app.domain.user_repository import UserRepository
from app.security.jwt import TokenError, decode_access_token
from app.services.call_service import CallService
from app.security.stream_token import read_live_call_ticket
from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    user_repository: UserRepository = Depends(get_user_repository),
) -> tuple[User, dict]:
    """The signed-in user and their token's claims."""
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

    # A password reset signs the user out everywhere.
    issued = payload.get("iat")
    if user.password_changed_at is not None and (
        not isinstance(issued, (int, float)) or issued < int(user.password_changed_at)
    ):
        raise _CREDENTIALS_ERROR

    return user, payload


_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="You do not have permission to perform this action.",
)

# The roles that work on calls. An admin and a management user are not
# among them: they are let in only where an endpoint names their role (see
# require_roles and get_finished_call_reader), so a new endpoint is closed
# to them unless it says otherwise.
STAFF_ROLES = CALL_TAKING_ROLES
REPORT_READERS = (UserRole.SUPERVISOR, UserRole.ADMIN, UserRole.MANAGEMENT)
# The call list and its counts: staff work from them, an admin only reads.
CALL_LIST_READERS = (*STAFF_ROLES, UserRole.ADMIN)
# Who opens a call only once it has ended.
FINISHED_CALL_READERS = (UserRole.ADMIN, UserRole.MANAGEMENT)


def get_signed_in_user(session: tuple[User, dict] = Depends(get_current_session)) -> User:
    """Whoever is signed in, in any role."""
    return session[0]


def get_current_user(user: User = Depends(get_signed_in_user)) -> User:
    """The signed-in member of staff (an ICR or a supervisor)."""
    if user.role not in STAFF_ROLES:
        raise _FORBIDDEN
    return user


def require_roles(*roles: UserRole):
    def _check(user: User = Depends(get_signed_in_user)) -> User:
        if user.role not in roles:
            raise _FORBIDDEN
        return user

    return _check


def get_finished_call_reader(
    call_id: str,
    user: User = Depends(get_signed_in_user),
    call_service: CallService = Depends(get_call_service),
) -> User:
    """Who may read this call: staff, any call; an admin or a management
    user, a call that has ended (never while it is live)."""
    if user.role in STAFF_ROLES:
        return user
    if user.role not in FINISHED_CALL_READERS:
        raise _FORBIDDEN
    # An unknown call raises as it does for everyone (404).
    if call_service.get_call(call_id).status != ConversationStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This call can be opened once it has ended.",
        )
    return user

def authenticate_live_call_ws(websocket: WebSocket, call_id: str) -> User | None:
    """Authenticate a live-call WebSocket by its `?ticket=` (see
    POST /api/v1/calls/{call_id}/live-token).

    The ticket must be ours, unexpired, issued for this call, belong to an
    active user and not have been used before. Access tokens are not
    accepted here, so they never travel in a URL.

    Returns None instead of raising HTTPException - HTTPException doesn't
    translate to WS close frames, so the caller closes the socket itself
    with an appropriate code.
    """
    claims = read_live_call_ticket(websocket.query_params.get("ticket"), call_id)
    if claims is None:
        return None

    services = websocket.app.state.services
    user_repository: UserRepository | None = services.user_repository
    if user_repository is None:
        return None
    user = user_repository.get_by_id(claims.user_id)
    if user is None or not user.is_active or user.role not in STAFF_ROLES:
        return None

    # Single use, across every instance: the first connection marks the
    # ticket as spent until it would have expired anyway.
    store = services.live_state_store
    if store is not None:
        ttl = max(1.0, claims.expires_at - time.time() + 1)
        try:
            spent = store.acquire_lock(f"live_call_ticket:{claims.ticket_id}", ttl) is None
        except Exception:
            logger.exception("Could not check the live-call ticket; refusing it")
            return None
        if spent:
            return None
    return user
