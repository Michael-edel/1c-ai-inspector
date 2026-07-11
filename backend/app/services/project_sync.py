import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Environment
from app.mcp.connector import McpConnector
from app.models import McpServer, Project


class ProjectSyncError(ValueError):
    """Raised when MCP project data cannot be normalized safely."""


def extract_project_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    raw: Any = result.get("projects")
    if raw is None:
        for item in result.get("content", []):
            if item.get("type") == "text":
                try:
                    raw = json.loads(item.get("text", ""))
                    if isinstance(raw, dict):
                        raw = raw.get("projects")
                except (TypeError, ValueError) as exc:
                    raise ProjectSyncError("MCP_PROJECTS_RESPONSE_INVALID") from exc
                break
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise ProjectSyncError("MCP_PROJECTS_RESPONSE_INVALID")
    return raw


class ProjectSyncService:
    def __init__(self, db: Session, endpoint_url: str):
        self.db = db
        self.endpoint_url = endpoint_url

    def persist(self, items: list[dict[str, Any]]) -> int:
        server = self.db.get(McpServer, "mcp_edt")
        if server is None:
            server = McpServer(
                id="mcp_edt",
                name="EDT MCP Server",
                endpoint_url=self.endpoint_url,
                status="ready",
            )
            self.db.add(server)
            self.db.flush()

        count = 0
        for item in items:
            external_id = str(item.get("id") or item.get("externalId") or "").strip()
            name = str(item.get("name") or "").strip()
            if not external_id or not name:
                raise ProjectSyncError("MCP_PROJECT_INVALID")
            environment = str(item.get("environment") or Environment.SANDBOX.value)
            if environment not in {value.value for value in Environment}:
                raise ProjectSyncError("MCP_PROJECT_ENVIRONMENT_INVALID")
            capabilities = item.get("availableCapabilities", item.get("capabilities", []))
            if not isinstance(capabilities, list) or any(not isinstance(value, str) for value in capabilities):
                raise ProjectSyncError("MCP_PROJECT_CAPABILITIES_INVALID")
            project = self.db.scalar(
                select(Project).where(
                    Project.mcp_server_id == server.id,
                    Project.external_id == external_id,
                )
            )
            if project is None:
                project = Project(
                    id="prj_" + hashlib.sha256(external_id.encode("utf-8")).hexdigest()[:32],
                    mcp_server_id=server.id,
                    external_id=external_id,
                    name=name,
                    environment=environment,
                    available_capabilities=json.dumps(capabilities, ensure_ascii=False),
                )
                self.db.add(project)
            else:
                project.name = name
                project.environment = environment
                project.available_capabilities = json.dumps(capabilities, ensure_ascii=False)
            count += 1
        self.db.commit()
        return count


async def sync_projects(
    db: Session,
    connector: McpConnector,
    tool_name: str,
    endpoint_url: str,
) -> int:
    result = await connector.call_tool(tool_name, {})
    items = extract_project_items(result)
    return ProjectSyncService(db, endpoint_url).persist(items)
