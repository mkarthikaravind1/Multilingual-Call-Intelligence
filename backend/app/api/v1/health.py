import hmac
import logging

from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.config import get_settings
from app.observability.metrics import REGISTRY

logger = logging.getLogger(__name__)

# Mounted at the root (not under /api/v1) where probes and scrapers expect it.
router = APIRouter(tags=["monitoring"])


@router.get("/health/live")
def liveness() -> dict:
    """The process is up and serving requests."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(request: Request) -> JSONResponse:
    """Every dependency this instance needs answers (database, shared
    live-state store). A load balancer should only route here when 200."""
    checks = request.app.state.services.health_checks or {}
    results: dict[str, str] = {}
    for name, check in checks.items():
        try:
            await run_in_threadpool(check)
            results[name] = "ok"
        except Exception as exc:
            logger.warning("Readiness check %r failed: %s", name, exc)
            results[name] = "unavailable"
    ready = all(result == "ok" for result in results.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ok" if ready else "unavailable", "checks": results},
    )


@router.get("/metrics")
def metrics(request: Request) -> Response:
    token = get_settings().metrics_token
    if token:
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied, f"Bearer {token}"):
            return PlainTextResponse("Unauthorized\n", status_code=401)
    return PlainTextResponse(REGISTRY.render(), media_type="text/plain; version=0.0.4")
