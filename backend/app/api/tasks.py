import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
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
from app.services.task_cancellation import TaskNotCancellable, request_task_cancellation

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


def _persist_task(
    db: Session,
    payload: TaskCreateRequest,
    project: Project,
    agent: Agent,
    settings: Settings,
    policy_snapshot,
    task_status: str,
    event_type: str,
    event_payload: dict[str, object],
    error_code: str | None = None,
) -> Task:
    now = datetime.now(timezone.utc)
    task_id = f"tsk_{uuid4().hex}"
    task = Task(
        id=task_id,
        project_id=project.id,
        agent_id=agent.id,
        status=task_status,
        request_json=json.dumps(payload.request, ensure_ascii=False),
        result_json=(
            json.dumps(
                {
                    "taskId": task_id,
                    "status": "failed",
                    "summary": event_payload["reason"],
                    "findings": [],
                    "objectsReviewed": [],
                    "validation": {"readOnly": True},
                    "sourceCoverage": "none",
                    "toolUsage": {"calls": 0, "durationMs": 0},
                    "modelUsage": {"inputTokens": 0, "outputTokens": 0, "estimatedCost": 0},
                    "limitations": [event_payload["reason"]],
                    "nextActions": [],
                },
                ensure_ascii=False,
            )
            if task_status == TaskStatus.FAILED.value
            else None
        ),
        available_at=now,
        last_error_code=error_code,
    )
    execution_snapshot = PromptExecutionSnapshot(
        id=f"snap_{uuid4().hex}",
        task_id=task_id,
        prompt_version=agent.prompt_version,
        model_provider=settings.model_provider,
        model_name=settings.model_name,
        policy_version=policy_snapshot.policy.version,
        policy_checksum=policy_snapshot.checksum,
        toolset_checksum=policy_snapshot.toolset_checksum,
    )
    db.add(task)
    db.flush()
    db.add_all(
        [
            execution_snapshot,
            TaskEvent(
                task_id=task_id,
                event_type=event_type,
                payload_json=json.dumps(event_payload, ensure_ascii=False),
            ),
        ]
    )
    return task


def _block_task(
    db: Session,
    payload: TaskCreateRequest,
    project: Project,
    agent: Agent,
    settings: Settings,
    policy_snapshot,
    code: str,
    reason: str,
) -> None:
    task = _persist_task(
        db,
        payload,
        project,
        agent,
        settings,
        policy_snapshot,
        TaskStatus.FAILED.value,
        "task_blocked",
        {"source": "api", "code": code, "reason": reason},
        code,
    )
    db.commit()
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "reasons": [reason], "taskId": task.id},
    )


@router.get("")
def list_tasks(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    """Return safe task metadata for the operator history view."""
    tasks = db.scalars(select(Task).order_by(Task.created_at.desc()).limit(50)).all()
    agent_ids = {task.agent_id for task in tasks}
    project_ids = {task.project_id for task in tasks}
    agents = {
        agent.id: agent
        for agent in db.scalars(select(Agent).where(Agent.id.in_(agent_ids))).all()
    }
    projects = {
        project.id: project
        for project in db.scalars(select(Project).where(Project.id.in_(project_ids))).all()
    }
    return [
        {
            "taskId": task.id,
            "status": task.status,
            "agentCode": agents[task.agent_id].code if task.agent_id in agents else None,
            "agentName": agents[task.agent_id].name if task.agent_id in agents else None,
            "projectId": task.project_id,
            "projectName": projects[task.project_id].name if task.project_id in projects else None,
            "environment": projects[task.project_id].environment if task.project_id in projects else None,
            "createdAt": task.created_at.isoformat(),
            "updatedAt": task.updated_at.isoformat(),
            "resultReady": task.result_json is not None,
            "lastErrorCode": task.last_error_code,
            "cancelRequested": task.cancel_requested,
        }
        for task in tasks
    ]


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
        "cancelRequested": task.cancel_requested,
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
    if project.environment not in {"sandbox", "test"} or project.environment != getattr(settings, "app_environment", "sandbox"):
        _block_task(
            db,
            payload,
            project,
            agent,
            settings,
            snapshot,
            "PROJECT_ENVIRONMENT_NOT_ALLOWED",
            f"Project environment '{project.environment}' is not allowed for this Inspector environment.",
        )
    try:
        project_capabilities = json.loads(project.available_capabilities)
    except (TypeError, ValueError):
        project_capabilities = None
    if not isinstance(project_capabilities, list) or any(not isinstance(item, str) for item in project_capabilities):
        _block_task(
            db,
            payload,
            project,
            agent,
            settings,
            snapshot,
            "PROJECT_CAPABILITIES_NOT_READY",
            "Project capabilities are not available for the selected agent.",
        )
    try:
        AgentRegistry().validate_capabilities(agent.code, set(project_capabilities))
    except ValueError:
        _block_task(
            db,
            payload,
            project,
            agent,
            settings,
            snapshot,
            "PROJECT_CAPABILITIES_NOT_READY",
            "Project capabilities do not satisfy the selected agent.",
        )

    task = _persist_task(
        db,
        payload,
        project,
        agent,
        settings,
        snapshot,
        TaskStatus.QUEUED.value,
        "task_created",
        {"source": "api"},
    )
    db.commit()
    return TaskResponse(
        task_id=task.id,
        status=task.status,
        policy_version=snapshot.policy.version,
        toolset_checksum=snapshot.toolset_checksum,
    )


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    try:
        request_task_cancellation(db, task, actor="api")
    except TaskNotCancellable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": str(exc)},
        ) from exc
    db.commit()
    return {
        "taskId": task.id,
        "status": task.status,
        "cancelRequested": task.cancel_requested,
        "lastErrorCode": task.last_error_code,
    }


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
    snapshot = db.scalar(
        select(PromptExecutionSnapshot)
        .where(PromptExecutionSnapshot.task_id == task_id)
        .order_by(PromptExecutionSnapshot.created_at.desc())
    )
    findings = db.scalars(
        select(Finding)
        .where(Finding.task_id == task_id)
        .order_by(Finding.created_at, Finding.id)
    ).all()
    report = json.loads(task.result_json)
    if snapshot is not None:
        report["execution"] = {
            "promptVersion": snapshot.prompt_version,
            "modelProvider": snapshot.model_provider,
            "modelName": snapshot.model_name,
            "policyVersion": snapshot.policy_version,
            "policyChecksum": snapshot.policy_checksum,
            "toolsetChecksum": snapshot.toolset_checksum,
        }
    report["persistedFindings"] = [
        {
            "id": item.id,
            "category": item.category,
            "severity": item.severity,
            "confidence": item.confidence,
            "objectFqn": item.object_fqn,
            "module": item.module,
            "method": item.method,
            "lineStart": item.line_start,
            "lineEnd": item.line_end,
            "description": item.description,
            "risk": item.risk,
            "recommendation": item.recommendation,
            "evidence": json.loads(item.evidence_json),
        }
        for item in findings
    ]
    return report


@router.get("/{task_id}/report/export")
def export_task_report(task_id: str, db: Session = Depends(get_db)) -> JSONResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    payload = {
        "taskId": task.id,
        "status": task.status,
        "report": task_report(task_id, db),
        "audit": task_audit(task_id, db).model_dump(),
    }
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{task.id}-report.json"'},
    )
