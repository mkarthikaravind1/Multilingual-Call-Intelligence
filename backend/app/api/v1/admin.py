from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.api.dependencies import (
    get_location_service,
    get_post_call_repair_service,
    get_user_management_service,
)
from app.api.security_dependencies import require_roles
from app.domain.user import User, UserRole
from app.services.auth_service import EmailAlreadyRegisteredError
from app.services.location_service import LocationService
from app.services.post_call_repair_service import PostCallRepairService
from app.services.user_management_service import UNCHANGED, UserManagementService

router = APIRouter(prefix="/admin", tags=["administration"])

_ADMINS = require_roles(UserRole.ADMIN)
_SUPERVISORS = require_roles(UserRole.SUPERVISOR, UserRole.ADMIN)


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Users -------------------------------------------------------------------


class UserResponse(_Response):
    user_id: str
    email: str
    role: UserRole
    is_active: bool
    created_at: float
    display_name: str | None
    location_id: str | None
    dial_target: str | None


class CreateUserRequest(_Request):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole
    display_name: str | None = Field(default=None, max_length=100)
    location_id: str | None = None
    # A phone number, or a SIP address (sip:name@host).
    dial_target: str | None = Field(default=None, max_length=200)


class UpdateUserRequest(_Request):
    role: UserRole | None = None
    is_active: bool | None = None
    # Left out: unchanged. null (or empty): cleared.
    display_name: str | None = Field(default=None, max_length=100)
    location_id: str | None = None
    dial_target: str | None = Field(default=None, max_length=200)


class ResetPasswordRequest(_Request):
    password: str = Field(min_length=8, max_length=128)


@router.get("/users", response_model=list[UserResponse])
def list_users(
    service: UserManagementService = Depends(get_user_management_service),
    _: User = Depends(_ADMINS),
) -> list[UserResponse]:
    return [UserResponse.model_validate(user) for user in service.list_users()]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    service: UserManagementService = Depends(get_user_management_service),
    _: User = Depends(_ADMINS),
) -> UserResponse:
    try:
        user = service.create_user(
            payload.email,
            payload.password,
            payload.role,
            display_name=payload.display_name,
            location_id=payload.location_id,
            dial_target=payload.dial_target,
        )
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=409, detail="A user with this email already exists.") from exc
    return UserResponse.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    payload: UpdateUserRequest,
    service: UserManagementService = Depends(get_user_management_service),
    admin: User = Depends(_ADMINS),
) -> UserResponse:
    sent = payload.model_fields_set
    return UserResponse.model_validate(
        service.update_user(
            user_id,
            admin,
            role=payload.role,
            is_active=payload.is_active,
            display_name=payload.display_name if "display_name" in sent else UNCHANGED,
            location_id=payload.location_id if "location_id" in sent else UNCHANGED,
            dial_target=payload.dial_target if "dial_target" in sent else UNCHANGED,
        )
    )


@router.post("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: str,
    payload: ResetPasswordRequest,
    service: UserManagementService = Depends(get_user_management_service),
    admin: User = Depends(_ADMINS),
) -> None:
    service.reset_password(user_id, payload.password, admin)


# --- Locations ---------------------------------------------------------------


class LocationResponse(_Response):
    location_id: str
    name: str
    phone_number: str
    is_active: bool
    created_at: float


class CreateLocationRequest(_Request):
    name: str = Field(min_length=1, max_length=100)
    # The number customers dial, with its country code.
    phone_number: str = Field(min_length=1, max_length=32)


class UpdateLocationRequest(_Request):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    phone_number: str | None = Field(default=None, min_length=1, max_length=32)
    is_active: bool | None = None


@router.get("/locations", response_model=list[LocationResponse])
def list_locations(
    service: LocationService = Depends(get_location_service),
    _: User = Depends(_ADMINS),
) -> list[LocationResponse]:
    return [LocationResponse.model_validate(l) for l in service.list_locations()]


@router.post(
    "/locations", response_model=LocationResponse, status_code=status.HTTP_201_CREATED
)
def create_location(
    payload: CreateLocationRequest,
    service: LocationService = Depends(get_location_service),
    _: User = Depends(_ADMINS),
) -> LocationResponse:
    return LocationResponse.model_validate(
        service.create_location(payload.name, payload.phone_number)
    )


@router.patch("/locations/{location_id}", response_model=LocationResponse)
def update_location(
    location_id: str,
    payload: UpdateLocationRequest,
    service: LocationService = Depends(get_location_service),
    _: User = Depends(_ADMINS),
) -> LocationResponse:
    return LocationResponse.model_validate(
        service.update_location(
            location_id,
            name=payload.name,
            phone_number=payload.phone_number,
            is_active=payload.is_active,
        )
    )


# --- Post-call repair --------------------------------------------------------


class PendingPostCallResponse(_Response):
    call_id: str
    first_seen_at: float
    attempts: int
    last_attempt_at: float | None
    last_error: str | None
    gave_up: bool


class RepairRunResponse(_Response):
    ran_at: float
    scanned: int
    pending: int
    repaired: int
    failed: int
    gave_up: int
    skipped_reason: str | None


class PostCallRepairStatusResponse(BaseModel):
    pending: list[PendingPostCallResponse]
    last_run: RepairRunResponse | None
    # False when the background sweep is switched off.
    background_enabled: bool


class RetryPostCallResponse(BaseModel):
    call_id: str
    repaired: bool


@router.get("/post-call", response_model=PostCallRepairStatusResponse)
def post_call_status(
    service: PostCallRepairService = Depends(get_post_call_repair_service),
    _: User = Depends(_SUPERVISORS),
) -> PostCallRepairStatusResponse:
    last_run = service.last_run
    return PostCallRepairStatusResponse(
        pending=[PendingPostCallResponse.model_validate(p) for p in service.pending()],
        last_run=None if last_run is None else RepairRunResponse.model_validate(last_run),
        background_enabled=service.background_interval_seconds > 0,
    )


@router.post("/post-call/repair", response_model=RepairRunResponse)
def run_post_call_repair(
    service: PostCallRepairService = Depends(get_post_call_repair_service),
    _: User = Depends(_SUPERVISORS),
) -> RepairRunResponse:
    return RepairRunResponse.model_validate(service.run())


@router.post("/post-call/{call_id}/retry", response_model=RetryPostCallResponse)
def retry_post_call(
    call_id: str,
    service: PostCallRepairService = Depends(get_post_call_repair_service),
    _: User = Depends(_SUPERVISORS),
) -> RetryPostCallResponse:
    return RetryPostCallResponse(call_id=call_id, repaired=service.retry(call_id) is not None)
