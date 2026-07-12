from typing import Any

from app.core.config import Settings
from app.mcp.policy import PolicySnapshot


def _configured_secret(value: str) -> bool:
    return bool(value.strip()) and not value.startswith("replace-with-")


def build_diagnostics(settings: Settings, snapshot: PolicySnapshot) -> dict[str, Any]:
    return {
        "mcp": {
            "endpointConfigured": bool(str(settings.mcp_server_url).strip()),
            "transport": settings.mcp_transport,
            "bridgeTokenConfigured": bool(settings.mcp_bridge_token),
            "policyTools": len(snapshot.published_tools),
            "projectsToolConfigured": bool(settings.mcp_projects_tool),
        },
        "model": {
            "provider": settings.model_provider,
            "model": settings.model_name,
            "endpointConfigured": bool(str(settings.model_api_url).strip()),
            "apiKeyConfigured": _configured_secret(settings.model_api_key),
        },
        "policy": {
            "policyId": snapshot.policy.policy_id,
            "version": snapshot.policy.version,
            "checksum": snapshot.checksum,
            "toolsetChecksum": snapshot.toolset_checksum,
        },
    }
