import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Project

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
