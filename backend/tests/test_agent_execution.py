import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agents.executor import execute_agent
from app.agents.registry import AgentRegistry
from app.core.config import get_settings
from app.modeling import ModelResult
from app.models import Base, ModelUsage, Task


class FakeAdapter:
    def complete(self, messages: list[dict[str, str]]) -> ModelResult:
        payload = json.loads(messages[-1]["content"].split("Task envelope:\n", 1)[1])
        report = {
            "taskId": payload["taskId"],
            "status": "completed",
            "summary": "No issues found",
            "findings": [],
            "objectsReviewed": [],
            "validation": {"readOnly": True},
            "toolUsage": {"calls": 0, "durationMs": 0},
            "modelUsage": {"inputTokens": 3, "outputTokens": 5, "estimatedCost": 0},
            "limitations": [],
            "nextActions": [],
        }
        return ModelResult(json.dumps(report), 3, 5)


class SchemaCheckingAdapter(FakeAdapter):
    def complete(self, messages: list[dict[str, str]]) -> ModelResult:
        assert "StructuredReport JSON Schema" in messages[0]["content"]
        assert '"taskId"' in messages[0]["content"]
        return super().complete(messages)


def test_agent_execution_persists_model_usage() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        task = Task(
            id="tsk_test",
            project_id="prj_test",
            agent_id="agt_test",
            status="running",
            request_json=json.dumps({"text": "inspect"}),
            available_at=datetime.now(timezone.utc),
        )
        session.add(task)
        session.commit()
        report = execute_agent(
            session,
            task,
            AgentRegistry().get("1c_code_assistant"),
            get_settings(),
            FakeAdapter(),
            tool_calls=[{"durationMs": 17}],
        )
        session.commit()
        assert report.status == "completed"
        assert report.tool_usage.calls == 1
        assert report.tool_usage.duration_ms == 17
        assert report.model_usage.input_tokens == 3
        assert report.model_usage.output_tokens == 5
        usage = session.scalars(select(ModelUsage).where(ModelUsage.task_id == task.id)).one()
        assert usage.input_tokens == 3
        assert usage.output_tokens == 5


def test_agent_prompt_contains_structured_report_schema() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        task = Task(
            id="tsk_schema",
            project_id="prj_test",
            agent_id="agt_test",
            status="running",
            request_json=json.dumps({"text": "inspect"}),
            available_at=datetime.now(timezone.utc),
        )
        session.add(task)
        session.commit()
        report = execute_agent(
            session,
            task,
            AgentRegistry().get("1c_code_assistant"),
            get_settings(),
            SchemaCheckingAdapter(),
        )
        assert report.status == "completed"


def test_module_audit_marks_partial_source_context() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        task = Task(
            id="tsk_partial_source",
            project_id="prj_test",
            agent_id="agt_test",
            status="running",
            request_json=json.dumps({"text": "audit"}),
            available_at=datetime.now(timezone.utc),
        )
        session.add(task)
        session.commit()
        report = execute_agent(
            session,
            task,
            AgentRegistry().get("1c_audit_agent"),
            get_settings(),
            FakeAdapter(),
            extra_context=[
                {
                    "source": "MCP",
                    "tool": "search_code",
                    "data": {
                        "content": [
                            {
                                "type": "text",
                                "text": "### Документ.ЗаказКлиента.МодульОбъекта\n```bsl\nВызов();\n```",
                            }
                        ]
                    },
                }
            ],
        )
        assert report.source_coverage == "partial"
        assert any("частичн" in item and "search_code" in item for item in report.limitations)
        assert report.next_actions
