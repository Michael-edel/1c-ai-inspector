from contextlib import asynccontextmanager
import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI

from app.api.agents import router as agents_router
from app.api.projects import router as projects_router
from app.api.patches import router as patches_router
from app.api.system import router as system_router
from app.api.tasks import router as tasks_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.mcp.policy import PolicyProvider
from app.services.jwks_auth import JwksProvider


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.policy_snapshot = PolicyProvider(settings.mcp_policy_path).load()
    app.state.discovered_tools = {}
    app.state.jwks_provider = (
        JwksProvider(str(settings.auth_jwks_url), settings.auth_jwks_cache_ttl_sec)
        if settings.auth_jwks_url
        else None
    )
    yield


app = FastAPI(title="1C AI Inspector", version="0.1.0", lifespan=lifespan)
configure_logging()
request_logger = logging.getLogger("app.http")
app.include_router(system_router)
app.include_router(projects_router)
app.include_router(patches_router)
app.include_router(tasks_router)
app.include_router(agents_router)


@app.middleware("http")
async def request_observability(request, call_next):
    request_id = uuid4().hex
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        request_logger.exception(
            "http_request_failed",
            extra={
                "fields": {
                    "requestId": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "durationMs": round((perf_counter() - started) * 1000, 2),
                }
            },
        )
        raise
    response.headers["X-Request-ID"] = request_id
    request_logger.info(
        "http_request",
        extra={
            "fields": {
                "requestId": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "durationMs": round((perf_counter() - started) * 1000, 2),
            }
        },
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
