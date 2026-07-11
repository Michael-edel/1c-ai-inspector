from fastapi import APIRouter

from app.agents.registry import AgentRegistry

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])
registry = AgentRegistry()


@router.get("")
def list_agents() -> list[dict[str, object]]:
    return registry.as_dicts()
