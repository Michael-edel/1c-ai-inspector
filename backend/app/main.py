from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.agents import router as agents_router
from app.api.projects import router as projects_router
from app.api.system import router as system_router
from app.api.tasks import router as tasks_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.mcp.policy import PolicyProvider


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.policy_snapshot = PolicyProvider(settings.mcp_policy_path).load()
    app.state.discovered_tools = {}
    yield


app = FastAPI(title="1C AI Inspector", version="0.1.0", lifespan=lifespan)
configure_logging()
app.include_router(system_router)
app.include_router(projects_router)
app.include_router(tasks_router)
app.include_router(agents_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
