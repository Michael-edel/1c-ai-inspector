import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.mcp.connector import McpConnector, ToolNotAllowedError
from app.models import Project
from app.services.project_sync import ProjectSyncError, sync_projects

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("")
def list_projects(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    projects = db.scalars(select(Project).order_by(Project.name)).all()
    return [
        {
            "id": project.id,
            "externalId": project.external_id,
            "name": project.name,
            "environment": project.environment,
            "availableCapabilities": json.loads(project.available_capabilities),
        }
        for project in projects
    ]


@router.post("/sync")
async def sync_project_list(request: Request, db: Session = Depends(get_db)) -> dict[str, int]:
    tool_name = request.app.state.settings.mcp_projects_tool
    if not tool_name:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Project sync is not configured")
    connector = McpConnector(str(request.app.state.settings.mcp_server_url), request.app.state.policy_snapshot)
    try:
        count = await sync_projects(
            db,
            connector,
            tool_name,
            str(request.app.state.settings.mcp_server_url),
        )
    except (httpx.HTTPError, RuntimeError, ToolNotAllowedError, ProjectSyncError) as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Project sync is unavailable") from exc
    finally:
        await connector.close()
    return {"synced": count}
