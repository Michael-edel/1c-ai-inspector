import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.tasks import TaskCreateRequest, create_task
from app.mcp.policy import PolicyProvider
from app.models import Base, Project, PromptExecutionSnapshot, Task, TaskEvent, ToolCall, TrafficUsage
from app.services.traffic import traffic_period


REQUIRED_CAPABILITIES = ["bsl.read", "code.search", "references.read"]


def test_create_task_persists_task_before_execution_snapshot() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    snapshot = PolicyProvider(Path(__file__).parents[2] / "mcp_policy.yaml").load()
    state = SimpleNamespace(
        policy_snapshot=snapshot,
        discovered_tools=set(snapshot.published_tools),
        settings=SimpleNamespace(model_provider="openai", model_name="gpt-5.5", app_environment="sandbox"),
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

        with pytest.raises(HTTPException) as cost_error:
            create_task(
                TaskCreateRequest(
                    projectId="prj_demo",
                    agentId="1c_code_assistant",
                    request={"text": "inspect"},
                ),
                request,
                session,
            )
        assert cost_error.value.detail["code"] == "MODEL_COST_CONFIRMATION_REQUIRED"
        assert cost_error.value.detail["estimate"]["currency"] == "KZT"

        response = create_task(
            TaskCreateRequest(
                projectId="prj_demo",
                agentId="1c_code_assistant",
                costConfirmed=True,
                request={"text": "inspect"},
            ),
            request,
            session,
        )

        assert response.status == "created"
        task = session.get(Task, response.task_id)
        snapshot_row = session.scalar(
            select(PromptExecutionSnapshot).where(
                PromptExecutionSnapshot.task_id == response.task_id
            )
        )
        assert task is not None
        assert snapshot_row is not None


def test_create_task_persists_server_enforced_full_source_step() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    snapshot = PolicyProvider(Path(__file__).parents[2] / "mcp_policy.yaml").load()
    state = SimpleNamespace(
        policy_snapshot=snapshot,
        discovered_tools=set(snapshot.published_tools),
        settings=SimpleNamespace(model_provider="openai", model_name="gpt-5.5", app_environment="sandbox"),
    )
    request = Request({"type": "http", "app": SimpleNamespace(state=state)})

    with Session(engine) as session:
        session.add(
            Project(
                id="prj_source_enforcement",
                mcp_server_id="mcp_edt",
                external_id="configuration:source-enforcement",
                name="Source enforcement",
                environment="sandbox",
                available_capabilities=json.dumps(REQUIRED_CAPABILITIES),
            )
        )
        session.commit()

        response = create_task(
            TaskCreateRequest(
                projectId="prj_source_enforcement",
                agentId="1c_code_assistant",
                costConfirmed=True,
                request={
                    "text": "Прочитай модуль документа ЗаказКлиента и найди процедуру ОбработкаЗаполнения",
                    "retrieval": [{"tool": "search_code", "arguments": {"query": "ОбработкаЗаполнения"}}],
                },
            ),
            request,
            session,
        )

        persisted = session.get(Task, response.task_id)
        assert persisted is not None
        retrieval = json.loads(persisted.request_json)["retrieval"]
        assert retrieval[0] == {
            "tool": "read_method_source",
            "arguments": {
                "module": "Документ.ЗаказКлиента.МодульОбъекта",
                "method": "ОбработкаЗаполнения",
            },
        }
        assert retrieval[1] == {
            "tool": "get_edt_metadata_summary",
            "arguments": {"objectType": "Документ", "name": "ЗаказКлиента"},
        }


def test_create_task_requires_confirmation_after_traffic_warning() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    snapshot = PolicyProvider(Path(__file__).parents[2] / "mcp_policy.yaml").load()
    state = SimpleNamespace(
        policy_snapshot=snapshot,
        discovered_tools=set(snapshot.published_tools),
        settings=SimpleNamespace(
            model_provider="openai",
            model_name="gpt-5.5",
            app_environment="sandbox",
            traffic_warning_bytes=5_000_000_000,
            traffic_critical_bytes=8_000_000_000,
            traffic_hard_limit_bytes=9_800_000_000,
        ),
    )
    request = Request({"type": "http", "app": SimpleNamespace(state=state)})
    with Session(engine) as session:
        session.add(Project(
            id="prj_traffic_warning",
            mcp_server_id="mcp_edt",
            external_id="configuration:traffic-warning",
            name="Traffic warning",
            environment="sandbox",
            available_capabilities=json.dumps(REQUIRED_CAPABILITIES),
        ))
        session.add(TrafficUsage(period=traffic_period(), used_bytes=5_100_000_000, reserved_bytes=0))
        session.commit()

        with pytest.raises(HTTPException) as error:
            create_task(
                TaskCreateRequest(
                    projectId="prj_traffic_warning",
                    agentId="1c_code_assistant",
                    costConfirmed=True,
                    request={"text": "inspect"},
                ),
                request,
                session,
            )
        assert error.value.detail["code"] == "TRAFFIC_CONFIRMATION_REQUIRED"

        response = create_task(
            TaskCreateRequest(
                projectId="prj_traffic_warning",
                agentId="1c_code_assistant",
                trafficConfirmed=True,
                costConfirmed=True,
                request={"text": "inspect"},
            ),
            request,
            session,
        )
        assert response.status == "created"


def test_create_task_blocks_environment_and_records_audit_without_tools() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    snapshot = PolicyProvider(Path(__file__).parents[2] / "mcp_policy.yaml").load()
    state = SimpleNamespace(
        policy_snapshot=snapshot,
        discovered_tools=set(snapshot.published_tools),
        settings=SimpleNamespace(model_provider="openai", model_name="gpt-5.5", app_environment="sandbox"),
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
                TaskCreateRequest(projectId="prj_test_environment", agentId="1c_code_assistant", costConfirmed=True, request={"text": "inspect"}),
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
        settings=SimpleNamespace(model_provider="openai", model_name="gpt-5.5", app_environment="sandbox"),
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
                TaskCreateRequest(projectId="prj_missing_capability", agentId="1c_code_assistant", costConfirmed=True, request={"text": "inspect"}),
                request,
                session,
            )

        assert error.value.status_code == 409
        assert error.value.detail["code"] == "PROJECT_CAPABILITIES_NOT_READY"
        blocked = session.scalar(select(Task).where(Task.project_id == "prj_missing_capability"))
        assert blocked is not None
        assert session.scalar(select(TaskEvent).where(TaskEvent.task_id == blocked.id)).event_type == "task_blocked"
        assert session.scalars(select(ToolCall).where(ToolCall.task_id == blocked.id)).all() == []


def test_create_task_blocks_plain_language_question_for_query_agent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    snapshot = PolicyProvider(Path(__file__).parents[2] / "mcp_policy.yaml").load()
    state = SimpleNamespace(
        policy_snapshot=snapshot,
        discovered_tools=set(snapshot.published_tools),
        settings=SimpleNamespace(model_provider="openai", model_name="gpt-5.5", app_environment="sandbox"),
    )
    request = Request({"type": "http", "app": SimpleNamespace(state=state)})

    with Session(engine) as session:
        session.add(Project(
            id="prj_query_guard",
            mcp_server_id="mcp_edt",
            external_id="configuration:query-guard",
            name="Query guard",
            environment="sandbox",
            available_capabilities=json.dumps(["query.validate", "metadata.read"]),
        ))
        session.commit()

        with pytest.raises(HTTPException) as error:
            create_task(
                TaskCreateRequest(
                    projectId="prj_query_guard",
                    agentId="1c_query_agent",
                    costConfirmed=True,
                    request={
                        "text": "Объясни процедуру РассчитатьСебестоимость",
                        "retrieval": [{"tool": "validate_query", "arguments": {"query": "ВЫБРАТЬ 1"}}],
                    },
                ),
                request,
                session,
            )

        assert error.value.detail["code"] == "AGENT_REQUEST_NOT_SUPPORTED"
        blocked = session.scalar(select(Task).where(Task.project_id == "prj_query_guard"))
        assert blocked is not None
        assert blocked.last_error_code == "AGENT_REQUEST_NOT_SUPPORTED"
