from fastapi.testclient import TestClient

from app.main import app


def test_ready_endpoint_blocks_before_database_when_toolset_is_not_ready() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/system/ready")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "AGENT_TOOLSET_NOT_READY"


def test_model_tables_are_registered() -> None:
    from app.models import Base

    assert {
        "projects",
        "tasks",
        "task_events",
        "tool_calls",
        "findings",
        "model_usage",
        "normalized_tools",
        "prompt_execution_snapshots",
    }.issubset(Base.metadata.tables)
