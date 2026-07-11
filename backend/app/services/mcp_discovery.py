import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.mcp.contracts import ToolContract
from app.mcp.policy import PolicySnapshot
from app.models import McpServer, NormalizedTool


class McpDiscoveryService:
    def __init__(self, db: Session, snapshot: PolicySnapshot, endpoint_url: str):
        self.db = db
        self.snapshot = snapshot
        self.endpoint_url = endpoint_url

    def persist(self, tools: list[ToolContract]) -> None:
        server = self.db.get(McpServer, "mcp_edt")
        if server is None:
            server = McpServer(
                id="mcp_edt",
                name="EDT MCP Server",
                endpoint_url=self.endpoint_url,
                status="ready",
            )
            self.db.add(server)
        else:
            server.endpoint_url = self.endpoint_url
            server.status = "ready"
            server.updated_at = datetime.now(timezone.utc)

        for tool in tools:
            tool_id = "tool_" + hashlib.sha256(tool.name.encode("utf-8")).hexdigest()[:32]
            existing = self.db.get(NormalizedTool, tool_id)
            values = {
                "original_name": tool.original_name or tool.name,
                "normalized_name": tool.name,
                "category": tool.category,
                "mode": tool.mode.value,
                "risk_level": tool.risk_level.value,
                "side_effects_json": json.dumps(
                    [item.value for item in tool.side_effects], separators=(",", ":")
                ),
                "contract_json": json.dumps(tool.model_dump(mode="json"), separators=(",", ":")),
                "policy_version": self.snapshot.policy.version,
                "toolset_checksum": self.snapshot.toolset_checksum,
                "publication_status": "published",
            }
            if existing is None:
                self.db.add(NormalizedTool(id=tool_id, **values))
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
                existing.updated_at = datetime.now(timezone.utc)
        self.db.commit()
