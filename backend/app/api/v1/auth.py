import math

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies import get_auth_service, get_login_throttle
from app.api.security_dependencies import get_current_user
from app.api.v1.auth_schemas import LoginRequest, TokenResponse
from app.domain.user import User
from app.security.jwt import create_access_token
from app.services.auth_service import AuthService, InvalidCredentialsError
from app.services.login_throttle import LoginThrottle

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    throttle: LoginThrottle | None = Depends(get_login_throttle),
) -> TokenResponse:
    address = request.client.host if request.client is not None else None
    if throttle is not None and throttle.locked(payload.email, address):
        minutes = math.ceil(throttle.window_seconds / 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed sign-in attempts. Try again in {minutes} minutes.",
            headers={"Retry-After": str(int(throttle.window_seconds))},
        )
    try:
        user = auth_service.authenticate(payload.email, payload.password)
    except InvalidCredentialsError:
        if throttle is not None:
            throttle.failed(payload.email, address)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    if throttle is not None:
        throttle.succeeded(payload.email)
    return TokenResponse(access_token=create_access_token(user))


@router.post("/refresh", response_model=TokenResponse)
def refresh(user: User = Depends(get_current_user)) -> TokenResponse:
    """A fresh access token for a signed-in user whose token has not expired
    yet. The browser calls this while a live call is in progress, so a long
    call never signs the agent out. The user is re-checked (still active) and
    the new token carries their current role."""
    return TokenResponse(access_token=create_access_token(user))
