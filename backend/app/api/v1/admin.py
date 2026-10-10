from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.api.dependencies import (
    get_category_admin,
    get_location_service,
    get_post_call_repair_service,
    get_user_management_service,
)
from app.api.security_dependencies import require_roles
from app.domain.user import User, UserRole
from app.services.auth_service import EmailAlreadyRegisteredError
from app.domain.complaint_category import MAX_CUSTOM_CATEGORY_NAME_LENGTH
from app.services.complaint_category_admin import (
    MAX_CATEGORY_DESCRIPTION_LENGTH,
    ComplaintCategoryAdminService,
)
from app.services.complaint_category_catalog import CatalogEntry
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


# --- Complaint categories ----------------------------------------------------


class ManagedCategoryResponse(BaseModel):
    # builtin:<name>, theme:<candidate id> or admin:<id>.
    key: str
    name: str
    # What counts as it, told to the detector; null for built-ins.
    description: str | None
    # built_in, theme (an accepted emerging theme) or admin (added here).
    source: str
    # Names it had before: complaints stored under them count under `name`.
    former_names: list[str]
    # When it was retired (detection no longer reports it); null: in use.
    retired_at: float | None
    # Built-in categories keep their names.
    can_rename: bool
    # "Other" stays: a complaint that fits nothing else needs somewhere to go.
    can_retire: bool


class CreateCategoryRequest(_Request):
    name: str = Field(min_length=1, max_length=MAX_CUSTOM_CATEGORY_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_CATEGORY_DESCRIPTION_LENGTH)


class UpdateCategoryRequest(_Request):
    # Each left out: unchanged.
    name: str | None = Field(default=None, min_length=1, max_length=MAX_CUSTOM_CATEGORY_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_CATEGORY_DESCRIPTION_LENGTH)
    # true: retire it; false: bring it back.
    retired: bool | None = None


def _category_response(entry: CatalogEntry) -> ManagedCategoryResponse:
    built_in = entry.source == "built_in"
    return ManagedCategoryResponse(
        key=entry.key,
        name=entry.category.name,
        description=entry.category.description,
        source=entry.source,
        former_names=list(entry.former_names),
        retired_at=entry.retired_at,
        can_rename=not built_in,
        can_retire=not (built_in and entry.category.name == "Other"),
    )


@router.get("/complaint-categories", response_model=list[ManagedCategoryResponse])
def list_complaint_categories(
    service: ComplaintCategoryAdminService = Depends(get_category_admin),
    _: User = Depends(_ADMINS),
) -> list[ManagedCategoryResponse]:
    """Every complaint category, retired ones included."""
    return [_category_response(entry) for entry in service.list_categories()]


@router.post(
    "/complaint-categories",
    response_model=ManagedCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_complaint_category(
    payload: CreateCategoryRequest,
    service: ComplaintCategoryAdminService = Depends(get_category_admin),
    admin: User = Depends(_ADMINS),
) -> ManagedCategoryResponse:
    return _category_response(service.add(payload.name, payload.description, admin.user_id))


@router.patch("/complaint-categories/{key}", response_model=ManagedCategoryResponse)
def update_complaint_category(
    key: str,
    payload: UpdateCategoryRequest,
    service: ComplaintCategoryAdminService = Depends(get_category_admin),
    admin: User = Depends(_ADMINS),
) -> ManagedCategoryResponse:
    """Rename a category, change what counts as it, retire it or bring it
    back. Complaints already stored keep their place: a renamed category's
    are shown under its new name, a retired one's stay in reports."""
    entry = None
    if payload.name is not None:
        entry = service.rename(key, payload.name, admin.user_id)
    if "description" in payload.model_fields_set:
        entry = service.describe(key, payload.description, admin.user_id)
    if payload.retired is not None:
        entry = (
            service.retire(key, admin.user_id)
            if payload.retired
            else service.restore(key, admin.user_id)
        )
    if entry is None:
        raise HTTPException(status_code=422, detail="Nothing to change was given.")
    return _category_response(entry)


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
