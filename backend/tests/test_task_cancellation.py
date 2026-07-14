from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.tasks import cancel_task
from app.models import Agent, Base, McpServer, Project, Task, TaskEvent
from app.services.task_cancellation import TaskNotCancellable, finalize_task_cancellation, request_task_cancellation


def make_task(session: Session, status: str) -> Task:
    session.add(McpServer(id="mcp_cancel", name="Cancel MCP", endpoint_url="http://mcp"))
    session.add(Agent(id="agt_cancel", code="1c_code_assistant", name="Code", prompt_version="1.0.0"))
    session.add(Project(
        id="prj_cancel",
        mcp_server_id="mcp_cancel",
        external_id="configuration:cancel",
        name="Cancel project",
        environment="sandbox",
        available_capabilities="[]",
    ))
    task = Task(
        id=f"tsk_{status}",
        project_id="prj_cancel",
        agent_id="agt_cancel",
        status=status,
        request_json="{}",
        available_at=datetime.now(timezone.utc),
    )
    session.add(task)
    session.commit()
    return task


def test_cancel_queued_task_is_terminal_and_audited() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        task = make_task(session, "queued")
        response = cancel_task(task.id, session)
        session.refresh(task)

        event_types = session.scalars(select(TaskEvent.event_type).where(TaskEvent.task_id == task.id)).all()

    assert response["status"] == "cancelled"
    assert response["cancelRequested"] is True
    assert task.status == "cancelled"
    assert task.last_error_code == "TASK_CANCELLED_BY_USER"
    assert "task_cancelled" in event_types


@pytest.mark.parametrize("active_status", ["discovering", "analyzing", "reporting", "running"])
def test_cancel_active_task_sets_cooperative_flag(active_status: str) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        task = make_task(session, active_status)
        request_task_cancellation(session, task, actor="test")
        session.commit()

        session.refresh(task)
        event_types = session.scalars(select(TaskEvent.event_type).where(TaskEvent.task_id == task.id)).all()

    assert task.status == active_status
    assert task.cancel_requested is True
    assert "task_cancel_requested" in event_types


def test_cancel_completed_task_returns_conflict() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        task = make_task(session, "completed")
        with pytest.raises(HTTPException) as error:
            cancel_task(task.id, session)

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "TASK_NOT_CANCELLABLE"


def test_worker_finalizes_requested_cancellation() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        task = make_task(session, "analyzing")
        task.cancel_requested = True
        finalize_task_cancellation(session, task, actor="worker")
        session.commit()
        status = task.status
        error_code = task.last_error_code

    assert status == "cancelled"
    assert error_code == "TASK_CANCELLED_BY_USER"
