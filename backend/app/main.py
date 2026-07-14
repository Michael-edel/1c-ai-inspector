from contextlib import asynccontextmanager
import asyncio
import logging
from time import perf_counter
from uuid import uuid4

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.agents import router as agents_router
from app.api.projects import router as projects_router
from app.api.patches import router as patches_router
from app.api.system import router as system_router
from app.api.tasks import router as tasks_router
from app.api.sandbox import router as sandbox_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_session_factory
from app.mcp.connector import McpConnector
from app.mcp.policy import PolicyError
from app.mcp.policy import PolicyProvider
from app.services.jwks_auth import JwksProvider
from app.services.mcp_discovery import McpDiscoveryService


async def _auto_discover_mcp(app: FastAPI) -> None:
    settings = app.state.settings
    logger = logging.getLogger("app.mcp")
    for attempt in range(1, 4):
        connector = McpConnector(
            str(settings.mcp_server_url),
            app.state.policy_snapshot,
            transport_mode=settings.mcp_transport,
            access_token=settings.mcp_bridge_token,
        )
        try:
            tools = await connector.discover_tools()
            with get_session_factory()() as db:
                McpDiscoveryService(
                    db,
                    app.state.policy_snapshot,
                    str(settings.mcp_server_url),
                ).persist(tools)
            app.state.discovered_tools = {tool.name: tool for tool in tools}
            logger.info(
                "mcp_auto_discovery_succeeded",
                extra={"fields": {"tools": len(tools), "attempt": attempt}},
            )
            return
        except (httpx.HTTPError, PolicyError, ValueError, RuntimeError, SQLAlchemyError):
            logger.warning(
                "mcp_auto_discovery_failed",
                extra={"fields": {"attempt": attempt}},
            )
        finally:
            await connector.close()
        await asyncio.sleep(min(2**attempt, 5))

    logger.warning("mcp_auto_discovery_unavailable")


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
    discovery_task = asyncio.create_task(_auto_discover_mcp(app))
    try:
        yield
    finally:
        discovery_task.cancel()
        await asyncio.gather(discovery_task, return_exceptions=True)


app = FastAPI(title="1C AI Inspector", version="0.6.0", lifespan=lifespan)
configure_logging()
request_logger = logging.getLogger("app.http")
app.include_router(system_router)
app.include_router(projects_router)
app.include_router(patches_router)
app.include_router(tasks_router)
app.include_router(agents_router)
if get_settings().sandbox_executor_enabled:
    app.include_router(sandbox_router)


@app.middleware("http")
async def request_observability(request, call_next):
    request_id = uuid4().hex
    started = perf_counter()
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            too_large = int(content_length) > request.app.state.settings.max_request_bytes
        except ValueError:
            too_large = True
        if too_large:
            response = JSONResponse(status_code=413, content={"detail": "REQUEST_TOO_LARGE"})
            _set_security_headers(response, request_id)
            return response
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
    _set_security_headers(response, request_id)
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


def _set_security_headers(response, request_id: str) -> None:
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
