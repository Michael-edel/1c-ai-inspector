from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.projects import router as projects_router
from app.api.system import router as system_router
from app.core.config import get_settings
from app.mcp.policy import PolicyProvider


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.policy_snapshot = PolicyProvider(settings.mcp_policy_path).load()
    yield


app = FastAPI(title="1C AI Inspector", version="0.1.0", lifespan=lifespan)
app.include_router(system_router)
app.include_router(projects_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
