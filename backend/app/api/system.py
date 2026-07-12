from fastapi import APIRouter, Depends, HTTPException, Request
import httpx
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.mcp.connector import McpConnector
from app.mcp.policy import PolicyError
from app.db.session import get_db
from app.models import PatchEvent, PatchPackageVersion, PatchProposal, Task, ToolCall
from app.api.dependencies import require_identity
from app.services.auth import AuthContext
from app.services.mcp_discovery import McpDiscoveryService
from app.services.capabilities import evaluate_capabilities
from app.services.diagnostics import build_diagnostics
from app.services.readiness import ReadinessGate

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/metrics")
def metrics(
    identity: AuthContext = Depends(require_identity),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        proposal_statuses = db.execute(
            select(PatchProposal.status, func.count()).group_by(PatchProposal.status)
        ).all()
        task_statuses = db.execute(select(Task.status, func.count()).group_by(Task.status)).all()
        tool_call_statuses = db.execute(
            select(ToolCall.status, func.count()).group_by(ToolCall.status)
        ).all()
        event_types = db.execute(select(PatchEvent.event_type, func.count()).group_by(PatchEvent.event_type)).all()
        package_versions = db.scalar(select(func.count()).select_from(PatchPackageVersion)) or 0
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="METRICS_UNAVAILABLE") from exc
    return {
        "status": "ok",
        "proposals": {"byStatus": _counts(proposal_statuses)},
        "tasks": {"byStatus": _counts(task_statuses)},
        "toolCalls": {"byStatus": _counts(tool_call_statuses)},
        "patchEvents": {"byType": _counts(event_types)},
        "packageVersions": package_versions,
    }


def _counts(rows: list[tuple[object, int]]) -> dict[str, int]:
    return {str(key): int(value) for key, value in rows}


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
        "discoveredTools": sorted(request.app.state.discovered_tools),
    }


@router.get("/readiness")
def readiness(request: Request) -> dict[str, object]:
    report = evaluate_capabilities(
        request.app.state.policy_snapshot,
        set(request.app.state.discovered_tools),
    )
    result = report.as_dict()
    result["policyChecksum"] = request.app.state.policy_snapshot.checksum
    result["database"] = "not_checked"
    result["mcp"] = "not_checked"
    return result


@router.get("/capabilities")
def capabilities(request: Request) -> dict[str, object]:
    report = evaluate_capabilities(
        request.app.state.policy_snapshot,
        set(request.app.state.discovered_tools),
    )
    return {
        "status": report.status,
        "published": sorted(request.app.state.policy_snapshot.published_tools),
        "missingByAgent": report.as_dict()["agentCapabilities"],
    }


@router.get("/diagnostics")
def diagnostics(request: Request) -> dict[str, object]:
    return build_diagnostics(
        request.app.state.settings,
        request.app.state.policy_snapshot,
    )


@router.get("/mcp/health")
async def mcp_health(request: Request) -> dict[str, object]:
    connector = McpConnector(
        str(request.app.state.settings.mcp_server_url),
        request.app.state.policy_snapshot,
        transport_mode=request.app.state.settings.mcp_transport,
        access_token=request.app.state.settings.mcp_bridge_token,
    )
    try:
        result = await connector.initialize()
    except (httpx.HTTPError, PolicyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="MCP server is unavailable") from exc
    finally:
        await connector.close()
    return {"status": "ok", "server": result.get("serverInfo", {})}


@router.get("/mcp/tools")
async def discover_mcp_tools(
    request: Request, db: Session = Depends(get_db)
) -> dict[str, object]:
    connector = McpConnector(
        str(request.app.state.settings.mcp_server_url),
        request.app.state.policy_snapshot,
        transport_mode=request.app.state.settings.mcp_transport,
        access_token=request.app.state.settings.mcp_bridge_token,
    )
    try:
        tools = await connector.discover_tools()
        McpDiscoveryService(
            db,
            request.app.state.policy_snapshot,
            str(request.app.state.settings.mcp_server_url),
        ).persist(tools)
    except (httpx.HTTPError, PolicyError, ValueError, RuntimeError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="MCP discovery is unavailable") from exc
    finally:
        await connector.close()
    request.app.state.discovered_tools = {tool.name: tool for tool in tools}
    return {
        "tools": [tool.model_dump(mode="json") for tool in tools],
        "toolsetChecksum": request.app.state.policy_snapshot.toolset_checksum,
    }


@router.get("/ready")
def ready(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    report = evaluate_capabilities(
        request.app.state.policy_snapshot,
        set(request.app.state.discovered_tools),
    )
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
