"""Adds baseline security headers to every HTTP response.

No Content-Security-Policy here: the interactive API docs load their assets
from a CDN. The web app's own headers are set by the nginx in front of it.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_BASE_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
)
_HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


class SecurityHeadersMiddleware:
    """Never overwrites a header a route has already set."""

    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self._headers = _BASE_HEADERS + ((_HSTS,) if hsts else ())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {name.lower() for name, _ in headers}
                headers.extend(h for h in self._headers if h[0] not in present)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
