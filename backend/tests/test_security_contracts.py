from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException

from app.api.sandbox import _require_owner, router as sandbox_router
from app.main import app
from app.mcp.policy import PolicyError, PolicyProvider
from app.services.auth import AuthContext


def test_policy_rejects_write_tools_before_activation(tmp_path: Path) -> None:
    path = tmp_path / "write-policy.yaml"
    path.write_text(
        "policyId: test\nversion: 1.0.0\ntools:\n"
        "  Write Module: {name: raw, category: bsl.write, mode: write}\n",
        encoding="utf-8",
    )
    with pytest.raises(PolicyError, match="cannot publish"):
        PolicyProvider(path).load()


def test_production_default_openapi_does_not_publish_sandbox_routes() -> None:
    assert not any(path.startswith("/api/v1/sandbox-executions") for path in app.openapi()["paths"])
    enabled_app = FastAPI()
    enabled_app.include_router(sandbox_router)
    assert "/api/v1/sandbox-executions" in enabled_app.openapi()["paths"]


def test_sandbox_metadata_requires_owner_role() -> None:
    _require_owner(AuthContext(subject="owner-1", role="owner", expires_at=1))
    with pytest.raises(HTTPException) as error:
        _require_owner(AuthContext(subject="maintainer-1", role="maintainer", expires_at=1))
    assert error.value.status_code == 403
    assert error.value.detail == "SANDBOX_OWNER_REQUIRED"
