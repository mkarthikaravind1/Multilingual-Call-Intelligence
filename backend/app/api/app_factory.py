from fastapi import FastAPI
from app.api.dependencies import ApiServices
from app.api.errors import register_exception_handlers
from app.api.v1.calls import router as calls_router
from app.api.v1.live import router as live_router
API_V1_PREFIX = "/api/v1"

def create_app(services: ApiServices) -> FastAPI:
    app = FastAPI(
        title="Multilingual Customer Interaction Intelligence API",
        version="1.0.0",
    )
    app.state.services = services
    register_exception_handlers(app)
    app.include_router(calls_router, prefix=API_V1_PREFIX)
    app.include_router(live_router, prefix=API_V1_PREFIX)
    return app