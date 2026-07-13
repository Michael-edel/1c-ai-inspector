import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.tasks import TaskCreateRequest, create_task
from app.mcp.policy import PolicyProvider
from app.models import Base, Project, PromptExecutionSnapshot, Task, TaskEvent, ToolCall


REQUIRED_CAPABILITIES = ["bsl.read", "code.search", "references.read"]


def test_create_task_persists_task_before_execution_snapshot() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    snapshot = PolicyProvider(Path(__file__).parents[2] / "mcp_policy.yaml").load()
    state = SimpleNamespace(
        policy_snapshot=snapshot,
        discovered_tools=set(snapshot.published_tools),
        settings=SimpleNamespace(model_provider="openai", model_name="test-model", app_environment="sandbox"),
    )
    request = Request({"type": "http", "app": SimpleNamespace(state=state)})

    with Session(engine) as session:
        session.add(
            Project(
                id="prj_demo",
                mcp_server_id="mcp_edt",
                external_id="configuration:demo",
                name="Demo",
                environment="sandbox",
                available_capabilities=json.dumps(REQUIRED_CAPABILITIES),
            )
        )
        session.commit()

        response = create_task(
            TaskCreateRequest(
                projectId="prj_demo",
                agentId="1c_code_assistant",
                request={"text": "inspect"},
            ),
            request,
            session,
        )

        assert response.status == "queued"
        task = session.get(Task, response.task_id)
        snapshot_row = session.scalar(
            select(PromptExecutionSnapshot).where(
                PromptExecutionSnapshot.task_id == response.task_id
            )
        )
        assert task is not None
        assert snapshot_row is not None


def test_create_task_blocks_environment_and_records_audit_without_tools() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    snapshot = PolicyProvider(Path(__file__).parents[2] / "mcp_policy.yaml").load()
    state = SimpleNamespace(
        policy_snapshot=snapshot,
        discovered_tools=set(snapshot.published_tools),
        settings=SimpleNamespace(model_provider="openai", model_name="test-model", app_environment="sandbox"),
    )
    request = Request({"type": "http", "app": SimpleNamespace(state=state)})

    with Session(engine) as session:
        session.add(Project(
            id="prj_test_environment",
            mcp_server_id="mcp_edt",
            external_id="configuration:test-environment",
            name="Test environment",
            environment="test",
            available_capabilities=json.dumps(REQUIRED_CAPABILITIES),
        ))
        session.commit()

        with pytest.raises(HTTPException) as error:
            create_task(
                TaskCreateRequest(projectId="prj_test_environment", agentId="1c_code_assistant", request={"text": "inspect"}),
                request,
                session,
            )

        assert error.value.status_code == 409
        assert error.value.detail["code"] == "PROJECT_ENVIRONMENT_NOT_ALLOWED"
        blocked = session.scalar(select(Task).where(Task.project_id == "prj_test_environment"))
        assert blocked is not None
        assert blocked.status == "failed"
        assert blocked.last_error_code == "PROJECT_ENVIRONMENT_NOT_ALLOWED"
        assert session.scalar(select(TaskEvent).where(TaskEvent.task_id == blocked.id)).event_type == "task_blocked"
        assert session.scalars(select(ToolCall).where(ToolCall.task_id == blocked.id)).all() == []


def test_create_task_blocks_missing_project_capability() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    snapshot = PolicyProvider(Path(__file__).parents[2] / "mcp_policy.yaml").load()
    state = SimpleNamespace(
        policy_snapshot=snapshot,
        discovered_tools=set(snapshot.published_tools),
        settings=SimpleNamespace(model_provider="openai", model_name="test-model", app_environment="sandbox"),
    )
    request = Request({"type": "http", "app": SimpleNamespace(state=state)})

    with Session(engine) as session:
        session.add(Project(
            id="prj_missing_capability",
            mcp_server_id="mcp_edt",
            external_id="configuration:missing-capability",
            name="Missing capability",
            environment="sandbox",
            available_capabilities=json.dumps(["code.search"]),
        ))
        session.commit()

        with pytest.raises(HTTPException) as error:
            create_task(
                TaskCreateRequest(projectId="prj_missing_capability", agentId="1c_code_assistant", request={"text": "inspect"}),
                request,
                session,
            )

        assert error.value.status_code == 409
        assert error.value.detail["code"] == "PROJECT_CAPABILITIES_NOT_READY"
        blocked = session.scalar(select(Task).where(Task.project_id == "prj_missing_capability"))
        assert blocked is not None
        assert session.scalar(select(TaskEvent).where(TaskEvent.task_id == blocked.id)).event_type == "task_blocked"
        assert session.scalars(select(ToolCall).where(ToolCall.task_id == blocked.id)).all() == []
