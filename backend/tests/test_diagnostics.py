from fastapi.testclient import TestClient

from app.main import app


def test_diagnostics_do_not_expose_model_api_key() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/system/diagnostics")
        assert response.status_code == 200
        body = response.json()
        assert body["model"]["apiKeyConfigured"] is True
        assert "test-key" not in str(body)
        assert body["mcp"]["policyTools"] == 8
        assert body["mcp"]["bridgeTokenConfigured"] in {True, False}
        assert body["auth"]["mode"] == "signed"
        assert body["auth"]["packageSigningConfigured"] in {True, False}
