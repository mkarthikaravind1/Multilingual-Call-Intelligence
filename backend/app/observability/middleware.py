import logging
import re
import time
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.logging import request_id_var
from app.observability.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS

logger = logging.getLogger("app.requests")

REQUEST_ID_HEADER = "x-request-id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
# Scrapes and probes would drown out real traffic in the logs.
_QUIET_PATHS = frozenset({"/health/live", "/health/ready", "/metrics"})


class RequestContextMiddleware:
    """Gives every HTTP request an id (reusing a sane incoming X-Request-ID),
    returns it in the response, logs the request and records metrics by
    route template (so /calls/{call_id} stays one series)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or {}).get(REQUEST_ID_HEADER.encode(), b"").decode(
            "latin-1"
        )
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers") or [])
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            duration = time.perf_counter() - started
            template = _route_template(scope)
            method = scope.get("method", "")
            HTTP_REQUESTS.inc(method, template, str(status_code))
            HTTP_REQUEST_DURATION.observe(duration, method, template)
            path = scope.get("path", "")
            if path not in _QUIET_PATHS:
                logger.log(
                    logging.WARNING if status_code >= 500 else logging.INFO,
                    "%s %s -> %d (%.1f ms)",
                    method,
                    path,
                    status_code,
                    duration * 1000,
                    extra={
                        "method": method,
                        "path": path,
                        "status": status_code,
                        "duration_ms": round(duration * 1000, 1),
                    },
                )
            request_id_var.reset(token)


def _route_template(scope: Scope) -> str:
    """The matched route's full path template, e.g. /api/v1/calls/{call_id}.
    Routes of an included router only know their path below its prefix, so
    the prefix is recovered from the actual request path."""
    route = scope.get("route")
    route_path = getattr(route, "path", None)
    if not route_path:
        return "unmatched"
    path = scope.get("path", "")
    try:
        concrete = getattr(route, "path_format", route_path).format(
            **(scope.get("path_params") or {})
        )
    except (KeyError, IndexError, ValueError):
        return route_path
    if path.endswith(concrete):
        return path[: len(path) - len(concrete)] + route_path
    return route_path
