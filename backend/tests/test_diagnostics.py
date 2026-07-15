from fastapi.testclient import TestClient

from app.main import app


def test_diagnostics_do_not_expose_model_api_key() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/system/diagnostics")
        assert response.status_code == 200
        body = response.json()
        assert body["model"]["apiKeyConfigured"] is True
        assert "test-key" not in str(body)
        assert body["mcp"]["policyTools"] == 10
        assert body["mcp"]["bridgeTokenConfigured"] in {True, False}
        assert body["auth"]["mode"] == "signed"
        assert body["auth"]["packageSigningConfigured"] in {True, False}


def test_health_returns_security_headers() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["Cache-Control"] == "no-store"
