from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.tasks import list_tasks
from app.models import Agent, Base, McpServer, Project, Task


def test_task_history_returns_safe_metadata_only() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    created_at = datetime.now(timezone.utc)

    with Session(engine) as session:
        session.add(McpServer(id="mcp_history", name="History MCP", endpoint_url="http://mcp"))
        session.add(Agent(id="agt_history", code="1c_code_assistant", name="1C Code Assistant", prompt_version="1.0.0"))
        session.add(Project(
            id="prj_history",
            mcp_server_id="mcp_history",
            external_id="configuration:history",
            name="History project",
            environment="sandbox",
            available_capabilities="[]",
        ))
        session.add(Task(
            id="tsk_history",
            project_id="prj_history",
            agent_id="agt_history",
            status="completed",
            request_json='{"text":"private request"}',
            result_json='{"summary":"private result"}',
            available_at=created_at,
            last_error_code=None,
        ))
        session.commit()

        history = list_tasks(session)

    assert history == [{
        "taskId": "tsk_history",
        "status": "completed",
        "agentCode": "1c_code_assistant",
        "agentName": "1C Code Assistant",
        "projectId": "prj_history",
        "projectName": "History project",
        "environment": "sandbox",
        "createdAt": history[0]["createdAt"],
        "updatedAt": history[0]["updatedAt"],
        "resultReady": True,
        "lastErrorCode": None,
    }]
    assert "private request" not in str(history)
    assert "private result" not in str(history)
