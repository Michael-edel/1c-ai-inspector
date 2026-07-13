from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Agent, Base, McpServer, Project, Task, TaskEvent, ToolCall
from app.services.retrieval import tool_call_fingerprint
from app.worker import (
    load_completed_tool_calls,
    recover_stale_tasks,
    refresh_task_heartbeat,
    release_task_lease,
    task_allows_next_tool,
)


def make_worker_task(session: Session, status: str = "running") -> Task:
    session.add(McpServer(id="mcp_worker", name="Worker MCP", endpoint_url="http://mcp"))
    session.add(Agent(id="agt_worker", code="1c_code_assistant", name="Code", prompt_version="1.0.0"))
    session.add(
        Project(
            id="prj_worker",
            mcp_server_id="mcp_worker",
            external_id="configuration:worker",
            name="Worker project",
            environment="sandbox",
            available_capabilities="[]",
        )
    )
    task = Task(
        id="tsk_worker",
        project_id="prj_worker",
        agent_id="agt_worker",
        status=status,
        request_json="{}",
        available_at=datetime.now(timezone.utc),
        locked_by="worker-a",
        locked_at=datetime.now(timezone.utc),
        heartbeat_at=datetime.now(timezone.utc),
        attempt=2,
    )
    session.add(task)
    session.commit()
    return task


def test_recovery_requeues_stale_task_and_records_event() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        task = make_worker_task(session)
        task.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session.commit()

        recovered = recover_stale_tasks(session, lease_timeout_sec=60)
        session.commit()
        session.refresh(task)
        events = session.scalars(select(TaskEvent).where(TaskEvent.task_id == task.id)).all()

    assert recovered == 1
    assert task.status == "queued"
    assert task.locked_by is None
    assert task.locked_at is None
    assert task.heartbeat_at is None
    assert task.last_error_code == "WORKER_LEASE_EXPIRED"
    assert [event.event_type for event in events] == ["task_recovered"]


def test_tool_gate_refreshes_heartbeat_and_release_clears_lease() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        task = make_worker_task(session)
        before = task.heartbeat_at

        assert task_allows_next_tool(session, task.id) is True
        session.refresh(task)
        refreshed = task.heartbeat_at
        release_task_lease(task)
        session.commit()
        session.refresh(task)

    assert refreshed is not None and before is not None and refreshed >= before
    assert task.locked_by is None
    assert task.locked_at is None
    assert task.heartbeat_at is None


def test_heartbeat_does_not_refresh_cancelled_task() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        task = make_worker_task(session)
        task.cancel_requested = True
        session.commit()

        assert refresh_task_heartbeat(session, task.id) is False
        session.rollback()
        session.refresh(task)

    assert task.heartbeat_at is not None


def test_completed_tool_call_is_loaded_into_retry_cache() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        task = make_worker_task(session)
        arguments = {"object": "Catalog.X"}
        session.add(
            ToolCall(
                id="call_worker",
                task_id=task.id,
                tool_name="read_source",
                mode="read-only",
                status="completed",
                input_json=json.dumps(arguments),
                output_json=json.dumps({"content": []}),
                duration_ms=18,
            )
        )
        session.commit()

        cache = load_completed_tool_calls(session, task.id)

    cached = cache[tool_call_fingerprint("read_source", arguments)]
    assert cached["status"] == "completed"
    assert cached["output"] == {"content": []}
    assert cached["durationMs"] == 18
