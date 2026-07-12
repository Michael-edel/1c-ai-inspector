from pathlib import Path
from types import SimpleNamespace

from fastapi import Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.tasks import TaskCreateRequest, create_task
from app.mcp.policy import PolicyProvider
from app.models import Base, Project, PromptExecutionSnapshot, Task


def test_create_task_persists_task_before_execution_snapshot() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    snapshot = PolicyProvider(Path(__file__).parents[2] / "mcp_policy.yaml").load()
    state = SimpleNamespace(
        policy_snapshot=snapshot,
        discovered_tools=set(snapshot.published_tools),
        settings=SimpleNamespace(model_provider="openai", model_name="test-model"),
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
                available_capabilities='["code.search"]',
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
