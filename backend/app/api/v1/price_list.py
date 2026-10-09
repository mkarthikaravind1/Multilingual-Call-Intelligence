"""The service centre's price list: supervisors view, upload, edit, export
and restore it. Supervisors only (not admins: prices are the service
floor's responsibility)."""

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from app.api.dependencies import get_price_list_service
from app.api.security_dependencies import require_roles
from app.api.v1.price_list_schemas import (
    PriceListIssueResponse,
    PriceListPreviewResponse,
    PriceListResponse,
    PriceListVersionResponse,
    SavePriceListRequest,
)
from app.domain.user import User, UserRole
from app.estimation.price_list_io import MAX_UPLOAD_BYTES, PriceListFileError
from app.services.price_list_service import (
    InvalidPriceListError,
    PriceListService,
    PriceListVersionNotFoundError,
)

router = APIRouter(prefix="/price-list", tags=["price-list"])

_SUPERVISORS_ONLY = require_roles(UserRole.SUPERVISOR)


def _invalid(error: InvalidPriceListError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": f"The price list has {len(error.errors)} problem(s); nothing was saved.",
            "errors": [
                PriceListIssueResponse.model_validate(issue).model_dump()
                for issue in error.errors
            ],
        },
    )


@router.get("", response_model=PriceListResponse)
def get_price_list(
    service: PriceListService = Depends(get_price_list_service),
    _: User = Depends(_SUPERVISORS_ONLY),
) -> PriceListResponse:
    return PriceListResponse.from_current(service.current())


@router.put("", response_model=PriceListResponse)
def save_price_list(
    request: SavePriceListRequest,
    service: PriceListService = Depends(get_price_list_service),
    user: User = Depends(_SUPERVISORS_ONLY),
):
    """Replace the whole price list (a new version; the old one can be
    restored). Nothing is saved when any row has a problem."""
    try:
        current = service.save(
            request.settings.to_domain(),
            tuple(row.to_domain() for row in request.rows),
            user=user.email,
            source=request.source,
            note=request.note,
        )
    except InvalidPriceListError as error:
        return _invalid(error)
    return PriceListResponse.from_current(current)


@router.post("/preview", response_model=PriceListPreviewResponse)
async def preview_upload(
    file: UploadFile = File(...),
    service: PriceListService = Depends(get_price_list_service),
    _: User = Depends(_SUPERVISORS_ONLY),
) -> PriceListPreviewResponse:
    """Read an uploaded .xlsx/.csv and check it; nothing is saved."""
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        # Reading a workbook takes up to seconds of CPU; off the event loop,
        # so live-call websockets keep being served meanwhile.
        preview = await run_in_threadpool(service.preview_upload, file.filename or "", content)
    except PriceListFileError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    return PriceListPreviewResponse.from_preview(preview)


@router.get("/export")
def export_price_list(
    file_format: Literal["xlsx", "csv"] = Query("xlsx", alias="format"),
    service: PriceListService = Depends(get_price_list_service),
    _: User = Depends(_SUPERVISORS_ONLY),
) -> Response:
    content, media_type, filename = service.export(file_format)
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/versions", response_model=list[PriceListVersionResponse])
def list_versions(
    service: PriceListService = Depends(get_price_list_service),
    _: User = Depends(_SUPERVISORS_ONLY),
) -> list[PriceListVersionResponse]:
    return [PriceListVersionResponse.model_validate(info) for info in service.versions()]


@router.post("/versions/{version_id}/restore", response_model=PriceListResponse)
def restore_version(
    version_id: int,
    service: PriceListService = Depends(get_price_list_service),
    user: User = Depends(_SUPERVISORS_ONLY),
):
    try:
        current = service.restore(version_id, user=user.email)
    except PriceListVersionNotFoundError:
        raise HTTPException(status_code=404, detail="That price list version no longer exists.")
    except InvalidPriceListError as error:
        return _invalid(error)
    return PriceListResponse.from_current(current)
