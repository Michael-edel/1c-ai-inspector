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
        assert "no_tools_discovered" in response.json()["reasons"]
