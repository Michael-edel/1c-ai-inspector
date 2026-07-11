from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/policy")
def policy_status(request: Request) -> dict[str, object]:
    snapshot = request.app.state.policy_snapshot
    return {
        "policyId": snapshot.policy.policy_id,
        "version": snapshot.policy.version,
        "checksum": snapshot.checksum,
        "publishedTools": sorted(snapshot.published_tools),
        "capabilitiesStatus": "ready",
    }


@router.get("/readiness")
def readiness(request: Request) -> dict[str, object]:
    snapshot = request.app.state.policy_snapshot
    return {
        "status": "ready",
        "policyLoaded": True,
        "normalizedToolsetBuilt": True,
        "onlyReadOnlyToolsPublished": len(snapshot.published_tools) == len(snapshot.policy.tools),
        "policyChecksum": snapshot.checksum,
        "database": "not_checked",
        "mcp": "not_checked",
    }
