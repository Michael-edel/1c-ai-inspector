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
        )
        session.commit()
        assert report.status == "completed"
        usage = session.scalars(select(ModelUsage).where(ModelUsage.task_id == task.id)).one()
        assert usage.input_tokens == 3
        assert usage.output_tokens == 5
