"""The audit log and the AI log, for administrators. Opening either is
itself recorded in the audit log (see app.api.audit.RECORDED_READS)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import get_ai_log, get_audit_log, get_user_repository
from app.api.security_dependencies import require_roles
from app.domain.user import User, UserRole
from app.domain.user_repository import UserRepository
from app.services.ai_log import AiLog, AiLogEntry, AiLogFilter, AiLogMode, AiOutcome
from app.services.audit_log import AuditFilter, AuditLog

router = APIRouter(prefix="/admin", tags=["administration"])

_ADMINS = require_roles(UserRole.ADMIN)
MAX_PAGE_SIZE = 200


class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Audit log ---------------------------------------------------------------


class AuditEntryResponse(_Response):
    entry_id: int | None
    occurred_at: float
    action: str
    method: str
    path: str
    status_code: int
    succeeded: bool
    user_id: str | None
    # The user's name as it is now; None when nobody was signed in or the
    # user no longer exists.
    user_name: str | None = None
    role: str | None
    target_type: str | None
    target_id: str | None
    ip_address: str | None
    request_id: str | None
    detail: dict[str, Any] | None


class AuditUserResponse(BaseModel):
    user_id: str
    name: str


class AuditLogResponse(BaseModel):
    entries: list[AuditEntryResponse]
    total: int
    # What the filters offer: every action with an entry, and every user.
    actions: list[str]
    users: list[AuditUserResponse]
    retention_days: float


@router.get("/audit-log", response_model=AuditLogResponse)
def read_audit_log(
    user_id: str | None = None,
    action: str | None = None,
    succeeded: bool | None = None,
    target_id: str | None = None,
    occurred_from: float | None = None,
    occurred_to: float | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    audit_log: AuditLog = Depends(get_audit_log),
    users: UserRepository = Depends(get_user_repository),
    _: User = Depends(_ADMINS),
) -> AuditLogResponse:
    """Who did what, newest first."""
    page = audit_log.search(
        AuditFilter(
            user_id=user_id or None,
            action=action or None,
            succeeded=succeeded,
            target_id=target_id or None,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
        ),
        limit=limit,
        offset=offset,
    )
    names = {user.user_id: user.name for user in users.list_all()}
    entries = []
    for entry in page.entries:
        response = AuditEntryResponse.model_validate(entry)
        response.user_name = names.get(entry.user_id) if entry.user_id else None
        entries.append(response)
    return AuditLogResponse(
        entries=entries,
        total=page.total,
        actions=list(audit_log.actions()),
        users=[
            AuditUserResponse(user_id=user_id, name=name)
            for user_id, name in sorted(names.items(), key=lambda item: item[1].casefold())
        ],
        retention_days=audit_log.retention_days,
    )


# --- AI log ------------------------------------------------------------------


class AiLogEntryResponse(_Response):
    entry_id: str
    call_id: str | None
    task: str
    model: str
    started_at: float
    duration_ms: float
    outcome: AiOutcome
    attempt: int
    prompt_chars: int
    answer_chars: int
    prompt_tokens: int | None
    completion_tokens: int | None
    note: str | None


class AiLogEntryDetailResponse(AiLogEntryResponse):
    # None when the text was not kept (AI_LOG_MODE=details).
    prompt: str | None
    answer: str | None


class AiLogTotalsResponse(_Response):
    requests: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    # Requests the provider gave no token counts for.
    uncounted: int


class AiLogResponse(BaseModel):
    entries: list[AiLogEntryResponse]
    total: int
    # Over everything the filters match, not only this page.
    totals: AiLogTotalsResponse
    tasks: list[str]
    mode: AiLogMode
    retention_days: float


@router.get("/ai-log", response_model=AiLogResponse)
def read_ai_log(
    call_id: str | None = None,
    task: str | None = None,
    outcome: AiOutcome | None = None,
    started_from: float | None = None,
    started_to: float | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    ai_log: AiLog = Depends(get_ai_log),
    _: User = Depends(_ADMINS),
) -> AiLogResponse:
    """The requests made to the AI, newest first, without their text."""
    page = ai_log.search(
        AiLogFilter(
            call_id=(call_id or "").strip() or None,
            task=task or None,
            outcome=outcome,
            started_from=started_from,
            started_to=started_to,
        ),
        limit=limit,
        offset=offset,
    )
    return AiLogResponse(
        entries=[AiLogEntryResponse.model_validate(entry) for entry in page.entries],
        total=page.total,
        totals=AiLogTotalsResponse.model_validate(page.totals),
        tasks=list(ai_log.tasks()),
        mode=ai_log.mode,
        retention_days=ai_log.retention_days,
    )


@router.get("/ai-log/{entry_id}", response_model=AiLogEntryDetailResponse)
def read_ai_log_entry(
    entry_id: str,
    ai_log: AiLog = Depends(get_ai_log),
    _: User = Depends(_ADMINS),
) -> AiLogEntryDetailResponse:
    """One request with what the AI was asked and what it answered."""
    entry: AiLogEntry | None = ai_log.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="This AI log entry does not exist.")
    return AiLogEntryDetailResponse.model_validate(entry)
