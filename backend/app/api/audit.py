"""Puts requests in the audit log (see app.services.audit_log).

Every request that changes something (POST, PUT, PATCH, DELETE) is
recorded, except the few listed in NOT_RECORDED; so are the reads listed in
RECORDED_READS. Nothing here reads a request's body or its query string:
an entry is made of who asked, the endpoint, the ids in its address and the
status the request ended with.
"""

import logging
import time
from typing import Any

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.domain.user import User
from app.observability.logging import request_id_var
from app.observability.middleware import route_template
from app.security.jwt import TokenError, decode_access_token
from app.services.audit_log import AuditEntry

logger = logging.getLogger(__name__)

_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Requests that change nothing although they are not GETs, by route as
# declared (without the /api/v1 prefix).
NOT_RECORDED = frozenset(
    {
        # A new access token for a user who is already signed in.
        "/auth/refresh",
        # A single-use ticket to open the live view of a call.
        "/calls/{call_id}/live-token",
        # Reads an uploaded price list and shows what saving it would do.
        "/price-list/preview",
    }
)

# Reads that are recorded: recordings, downloads and the logs themselves.
RECORDED_READS = frozenset(
    {
        "/calls/{call_id}/recording/audio",
        "/reports/complaints/export",
        "/reports/performance/export",
        "/price-list/export",
        "/learning/training-data/export",
        "/admin/audit-log",
        "/admin/ai-log",
        "/admin/ai-log/{entry_id}",
    }
)

# Who made a request that carries no user: the telephony provider's webhooks.
_TELEPHONY_PREFIX = "/telephony/"
TELEPHONY_ROLE = "telephony"

_STATE_KEY = "audit"


def note_user(request: Request, user: User) -> None:
    """Record the request as this user's (signing in carries no token)."""
    _notes(request.scope)["user"] = (user.user_id, user.role.value)


def note_target(request: Request, target_type: str, target_id: str) -> None:
    """Say what the request made, when its address does not: a new call,
    user, location or category has its id only in the answer."""
    _notes(request.scope)["target"] = (target_type, target_id)


def note_detail(request: Request, **detail: Any) -> None:
    """Add ids and the like to the request's audit entry. Never pass
    anything the user typed about a customer, or a secret."""
    _notes(request.scope).setdefault("detail", {}).update(detail)


def _notes(scope: Scope) -> dict[str, Any]:
    return scope.setdefault("state", {}).setdefault(_STATE_KEY, {})


class AuditMiddleware:
    def __init__(self, app: ASGIApp, api_prefix: str = "") -> None:
        self.app = app
        self._api_prefix = api_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status_code = 500

        async def send_noting_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_noting_status)
        finally:
            try:
                self._record(scope, status_code)
            except Exception:
                # The request has been answered: a log that cannot be
                # written must not turn that into an error.
                logger.exception("Could not add a request to the audit log")

    def _record(self, scope: Scope, status_code: int) -> None:
        services = getattr(scope["app"].state, "services", None)
        audit_log = getattr(services, "audit_log", None)
        route = scope.get("route")
        if audit_log is None or route is None:
            return
        template = route_template(scope)
        declared = template.removeprefix(self._api_prefix)
        method = scope.get("method", "")
        if declared in NOT_RECORDED:
            return
        if method not in _CHANGING_METHODS and declared not in RECORDED_READS:
            return

        notes = scope.get("state", {}).get(_STATE_KEY, {})
        user_id, role = notes.get("user") or _token_user(scope)
        if user_id is None and declared.startswith(_TELEPHONY_PREFIX):
            role = TELEPHONY_ROLE
        params = dict(scope.get("path_params") or {})
        target_type, target_id = notes.get("target") or _target(params)
        detail = dict(notes.get("detail") or {})
        if len(params) > 1:
            detail.update({name: str(value) for name, value in params.items()})
        client = scope.get("client")
        request_id = request_id_var.get()
        audit_log.record(
            AuditEntry(
                occurred_at=time.time(),
                action=getattr(route, "name", "") or declared,
                method=method,
                path=template,
                status_code=status_code,
                user_id=user_id,
                role=role,
                target_type=target_type,
                target_id=target_id,
                ip_address=client[0] if client else None,
                request_id=None if request_id == "-" else request_id,
                detail=detail or None,
            )
        )


def _token_user(scope: Scope) -> tuple[str | None, str | None]:
    """The user id and role in the request's access token; (None, None)
    without a valid one. Read from the token alone: an entry is made for
    refused requests too, and never costs a database read."""
    header = dict(scope.get("headers") or {}).get(b"authorization", b"").decode("latin-1")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None, None
    try:
        claims = decode_access_token(token.strip())
    except TokenError:
        return None, None
    user_id, role = claims.get("sub"), claims.get("role")
    return (
        user_id if isinstance(user_id, str) else None,
        role if isinstance(role, str) else None,
    )


def _target(params: dict[str, Any]) -> tuple[str | None, str | None]:
    """What the request was about: the last id in its address, e.g.
    /calls/{call_id}/hold -> ("call", "<the id>")."""
    if not params:
        return None, None
    name, value = list(params.items())[-1]
    return name.removesuffix("_id"), str(value)
