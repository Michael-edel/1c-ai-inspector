from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_policy_readiness() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/system/readiness")
        assert response.status_code == 200
        assert response.json()["onlyReadOnlyToolsPublished"] is True
        assert response.json()["status"] == "not_ready"
        assert response.json()["capabilitiesStatus"] == "not_discovered"
        assert "mcp_tools_not_discovered" in response.json()["reasons"]
        assert "agent_capabilities_missing" not in response.json()["reasons"]


def test_task_creation_is_blocked_until_toolset_is_ready() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/tasks",
            json={"projectId": "prj_1", "agentId": "agt_1", "request": {"text": "test"}},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "AGENT_TOOLSET_NOT_READY"


def test_agents_endpoint_lists_v01_agents() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/agents")
        assert response.status_code == 200
    assert {item["code"] for item in response.json()} == {
            "1c_code_assistant",
            "1c_query_agent",
            "1c_audit_agent",
    }


def test_capabilities_endpoint_reports_discovery_gap() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/system/capabilities")
        assert response.status_code == 200
        assert response.json()["status"] == "not_ready"
        assert response.json()["missingByAgent"] == {}
