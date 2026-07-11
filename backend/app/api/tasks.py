import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import TaskStatus
from app.db.session import get_db
from app.models import Agent, Project, PromptExecutionSnapshot, Task, TaskEvent
from app.services.readiness import ReadinessGate

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


class TaskCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(alias="projectId", min_length=1)
    agent_id: str = Field(alias="agentId", min_length=1)
    request: dict[str, object] = Field(default_factory=dict)


class TaskResponse(BaseModel):
    task_id: str
    status: str
    policy_version: str
    toolset_checksum: str


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskResponse:
    snapshot = request.app.state.policy_snapshot
    readiness = ReadinessGate().evaluate(snapshot)
    if readiness.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "AGENT_TOOLSET_NOT_READY", "reasons": list(readiness.reasons)},
        )

    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    agent = db.get(Agent, payload.agent_id)
    if agent is None or not agent.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    settings: Settings = request.app.state.settings
    now = datetime.now(timezone.utc)
    task_id = f"tsk_{uuid4().hex}"
    task = Task(
        id=task_id,
        project_id=project.id,
        agent_id=agent.id,
        status=TaskStatus.CREATED.value,
        request_json=json.dumps(payload.request, ensure_ascii=False),
        available_at=now,
    )
    execution_snapshot = PromptExecutionSnapshot(
        id=f"snap_{uuid4().hex}",
        task_id=task_id,
        prompt_version=agent.prompt_version,
        model_provider=settings.model_provider,
        model_name=settings.model_name,
        policy_version=snapshot.policy.version,
        policy_checksum=snapshot.checksum,
        toolset_checksum=snapshot.toolset_checksum,
    )
    db.add_all(
        [
            task,
            execution_snapshot,
            TaskEvent(
                task_id=task_id,
                event_type="task_created",
                payload_json='{"source":"api"}',
            ),
        ]
    )
    db.commit()
    return TaskResponse(
        task_id=task_id,
        status=task.status,
        policy_version=snapshot.policy.version,
        toolset_checksum=snapshot.toolset_checksum,
    )
