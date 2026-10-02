from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_auth_service
from app.api.security_dependencies import get_current_user
from app.api.v1.auth_schemas import LoginRequest, TokenResponse
from app.domain.user import User
from app.security.jwt import create_access_token
from app.services.auth_service import AuthService, InvalidCredentialsError

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    try:
        user = auth_service.authenticate(payload.email, payload.password)
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    return TokenResponse(access_token=create_access_token(user))


@router.post("/refresh", response_model=TokenResponse)
def refresh(user: User = Depends(get_current_user)) -> TokenResponse:
    """A fresh access token for a signed-in user whose token has not expired
    yet. The browser calls this while a live call is in progress, so a long
    call never signs the agent out. The user is re-checked (still active) and
    the new token carries their current role."""
    return TokenResponse(access_token=create_access_token(user))
