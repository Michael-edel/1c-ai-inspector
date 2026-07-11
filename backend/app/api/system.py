from fastapi import APIRouter, Depends, HTTPException, Request
import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.mcp.connector import McpConnector
from app.mcp.policy import PolicyError
from app.db.session import get_db
from app.services.readiness import ReadinessGate

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/policy")
def policy_status(request: Request) -> dict[str, object]:
    snapshot = request.app.state.policy_snapshot
    return {
        "policyId": snapshot.policy.policy_id,
        "version": snapshot.policy.version,
        "checksum": snapshot.checksum,
        "publishedTools": sorted(snapshot.published_tools),
        "normalizedTools": sorted(snapshot.normalized_tools),
        "toolsetChecksum": snapshot.toolset_checksum,
        "capabilitiesStatus": "ready" if snapshot.normalized_tools else "not_discovered",
    }


@router.get("/readiness")
def readiness(request: Request) -> dict[str, object]:
    report = ReadinessGate().evaluate(request.app.state.policy_snapshot)
    result = report.as_dict()
    result["policyChecksum"] = request.app.state.policy_snapshot.checksum
    result["database"] = "not_checked"
    result["mcp"] = "not_checked"
    return result


@router.get("/mcp/tools")
async def discover_mcp_tools(request: Request) -> dict[str, object]:
    connector = McpConnector(str(request.app.state.settings.mcp_server_url), request.app.state.policy_snapshot)
    try:
        tools = await connector.discover_tools()
    except (httpx.HTTPError, PolicyError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="MCP server is unavailable") from exc
    return {
        "tools": [tool.model_dump(mode="json") for tool in tools],
        "toolsetChecksum": request.app.state.policy_snapshot.toolset_checksum,
    }


@router.get("/ready")
def ready(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    report = ReadinessGate().evaluate(request.app.state.policy_snapshot)
    if report.status != "ready":
        raise HTTPException(
            status_code=503,
            detail={"code": "AGENT_TOOLSET_NOT_READY", "reasons": list(report.reasons)},
        )
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail={"code": "DATABASE_UNAVAILABLE"}) from exc
    return {"status": "ready", "database": "ok", "policy": "ready"}
