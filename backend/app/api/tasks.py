import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import TaskStatus
from app.db.session import get_db
from app.agents.registry import AgentRegistry
from app.models import Agent, Finding, ModelUsage, Project, PromptExecutionSnapshot, Task, TaskEvent, ToolCall
from app.services.readiness import ReadinessGate
from app.services.capabilities import evaluate_capabilities

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


class TaskAuditResponse(BaseModel):
    task_id: str
    status: str
    events: list[dict[str, object]]
    tool_calls: list[dict[str, object]]
    model_usage: list[dict[str, object]]


@router.get("/{task_id}")
def task_status(task_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return {
        "taskId": task.id,
        "status": task.status,
        "attempt": task.attempt,
        "resultReady": task.result_json is not None,
        "lastErrorCode": task.last_error_code,
    }


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskResponse:
    snapshot = request.app.state.policy_snapshot
    readiness = evaluate_capabilities(snapshot, set(request.app.state.discovered_tools))
    if readiness.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "AGENT_TOOLSET_NOT_READY", "reasons": list(readiness.reasons)},
        )

    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    agent = db.scalar(
        select(Agent).where(or_(Agent.id == payload.agent_id, Agent.code == payload.agent_id))
    )
    if agent is None or not agent.enabled:
        try:
            definition = AgentRegistry().get(payload.agent_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found") from exc
        agent = Agent(
            id=f"agt_{uuid4().hex}",
            code=definition.code,
            name=definition.name,
            prompt_version=definition.prompt_version,
            enabled=True,
        )
        db.add(agent)
        db.flush()

    settings: Settings = request.app.state.settings
    now = datetime.now(timezone.utc)
    task_id = f"tsk_{uuid4().hex}"
    task = Task(
        id=task_id,
        project_id=project.id,
        agent_id=agent.id,
        status=TaskStatus.QUEUED.value,
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
    db.add(task)
    db.flush()
    db.add_all(
        [
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


@router.get("/{task_id}/audit", response_model=TaskAuditResponse)
def task_audit(task_id: str, db: Session = Depends(get_db)) -> TaskAuditResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    events = db.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.created_at)).all()
    calls = db.scalars(select(ToolCall).where(ToolCall.task_id == task_id).order_by(ToolCall.created_at)).all()
    usage = db.scalars(select(ModelUsage).where(ModelUsage.task_id == task_id).order_by(ModelUsage.created_at)).all()
    return TaskAuditResponse(
        task_id=task.id,
        status=task.status,
        events=[{"type": event.event_type, "payload": json.loads(event.payload_json)} for event in events],
        tool_calls=[
            {
                "id": call.id,
                "toolName": call.tool_name,
                "mode": call.mode,
                "status": call.status,
                "durationMs": call.duration_ms,
                "errorCode": call.error_code,
            }
            for call in calls
        ],
        model_usage=[
            {
                "provider": item.provider,
                "model": item.model,
                "inputTokens": item.input_tokens,
                "outputTokens": item.output_tokens,
                "estimatedCost": item.estimated_cost,
            }
            for item in usage
        ],
    )


@router.get("/{task_id}/report")
def task_report(task_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if not task.result_json:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Report is not ready")
    findings = db.scalars(select(Finding).where(Finding.task_id == task_id)).all()
    report = json.loads(task.result_json)
    report["persistedFindings"] = [
        {
            "id": item.id,
            "severity": item.severity,
            "category": item.category,
            "objectFqn": item.object_fqn,
            "evidence": json.loads(item.evidence_json),
        }
        for item in findings
    ]
    return report
