import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.dependencies import ApiServices
from app.api.errors import register_exception_handlers
from app.api.v1.calls import router as calls_router
from app.api.v1.calls import stats_router as call_stats_router
from app.api.v1.live import router as live_router
from app.api.v1.learning import router as learning_router
API_V1_PREFIX = "/api/v1"
from app.api.v1.auth import router as auth_router
from app.api.v1.telephony import router as telephony_router
from app.api.v1.telephony_ws import router as telephony_ws_router
from app.api.v1.escalations import router as escalations_router
from app.api.v1.complaints import call_complaints_router
from app.api.v1.complaints import emerging_router as emerging_complaints_router
from app.api.v1.complaints import router as complaints_router
from app.api.v1.admin import router as admin_router
from app.api.v1.price_list import router as price_list_router
from app.api.v1.reports import router as reports_router
from app.api.v1.health import router as health_router
from app.api.v1.test_calls import router as test_calls_router
from app.core.config import get_settings
from app.observability.middleware import RequestContextMiddleware

def create_app(services: ApiServices) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        jobs = services.background_jobs
        if jobs is not None:
            jobs.start()
        if services.warm_up is not None:
            threading.Thread(target=services.warm_up, name="model-warm-up", daemon=True).start()
        try:
            yield
        finally:
            if jobs is not None:
                jobs.stop()

    app = FastAPI(
        title="Multilingual Customer Interaction Intelligence API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    # Outermost, so it also times and tags CORS preflights and errors.
    app.add_middleware(RequestContextMiddleware)
    app.state.services = services
    register_exception_handlers(app)
    app.include_router(calls_router, prefix=API_V1_PREFIX)
    app.include_router(call_stats_router, prefix=API_V1_PREFIX)
    app.include_router(live_router, prefix=API_V1_PREFIX)
    app.include_router(learning_router, prefix=API_V1_PREFIX)
    app.include_router(auth_router, prefix=API_V1_PREFIX)
    app.include_router(telephony_router, prefix=API_V1_PREFIX)
    app.include_router(telephony_ws_router, prefix=API_V1_PREFIX)
    app.include_router(escalations_router, prefix=API_V1_PREFIX)
    app.include_router(complaints_router, prefix=API_V1_PREFIX)
    app.include_router(call_complaints_router, prefix=API_V1_PREFIX)
    app.include_router(emerging_complaints_router, prefix=API_V1_PREFIX)
    app.include_router(admin_router, prefix=API_V1_PREFIX)
    app.include_router(price_list_router, prefix=API_V1_PREFIX)
    app.include_router(reports_router, prefix=API_V1_PREFIX)
    app.include_router(test_calls_router, prefix=API_V1_PREFIX)
    app.include_router(health_router)
    return app