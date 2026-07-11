from fastapi import APIRouter, Request

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
