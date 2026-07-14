from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings_kwargs() -> dict[str, object]:
    return {
        "_env_file": None,
        "database_url": "postgresql+psycopg://runtime:secret@localhost:5432/inspector",
        "migration_database_url": "postgresql+psycopg://migration:secret@localhost:5432/inspector",
        "mcp_server_url": "http://localhost:8001/mcp",
        "model_api_key": "model-secret",
        "inspector_auth_secret": "c" * 32,
        "app_environment": "test",
    }


def make_settings(**overrides: object) -> Settings:
    values = _settings_kwargs()
    values.update({"mcp_policy_path": Path("mcp_policy.yaml"), **overrides})
    return Settings(**values)


def test_secret_rotation_requires_a_deadline() -> None:
    with pytest.raises(ValidationError, match="PREVIOUS_UNTIL"):
        Settings(**_settings_kwargs(), inspector_auth_secret_previous="p" * 32)
    with pytest.raises(ValidationError, match="PREVIOUS is required"):
        Settings(**_settings_kwargs(), inspector_auth_secret_previous_until=100)


def test_secret_rotation_rejects_reusing_current_secret() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        Settings(
            **_settings_kwargs(),
            inspector_auth_secret_previous="c" * 32,
            inspector_auth_secret_previous_until=100,
        )


def test_jwks_mode_requires_external_issuer_configuration() -> None:
    with pytest.raises(ValidationError, match="AUTH_JWKS_URL"):
        Settings(**_settings_kwargs(), inspector_auth_mode="jwks")

    settings = Settings(
        **_settings_kwargs(),
        inspector_auth_mode="jwks",
        auth_jwks_url="https://issuer.test/.well-known/jwks.json",
        auth_issuer="https://issuer.test",
        auth_audience="inspector",
        inspector_package_signing_secret="s" * 32,
    )
    assert settings.inspector_auth_mode == "jwks"


def test_worker_heartbeat_interval_must_be_less_than_lease_timeout() -> None:
    with pytest.raises(ValidationError, match="WORKER_HEARTBEAT_INTERVAL_SEC"):
        make_settings(worker_heartbeat_interval_sec=300, worker_lease_timeout_sec=300)


def test_worker_heartbeat_interval_defaults_to_safe_value() -> None:
    settings = make_settings()

    assert settings.worker_heartbeat_interval_sec == 15
    assert settings.worker_heartbeat_interval_sec < settings.worker_lease_timeout_sec


def test_execution_limits_have_safe_defaults_and_reject_zero() -> None:
    settings = make_settings()

    assert settings.max_result_chars == 500_000
    assert settings.max_findings == 100
    assert settings.max_methods_read == 10
    with pytest.raises(ValidationError):
        make_settings(max_result_chars=0)
    with pytest.raises(ValidationError):
        make_settings(max_findings=0)
    with pytest.raises(ValidationError):
        make_settings(max_methods_read=0)


def test_model_retries_have_a_bounded_default() -> None:
    settings = make_settings()

    assert settings.model_retries == 1
    with pytest.raises(ValidationError):
        make_settings(model_retries=4)
