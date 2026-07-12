import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings_kwargs() -> dict[str, object]:
    return {
        "database_url": "postgresql+psycopg://runtime:secret@localhost:5432/inspector",
        "migration_database_url": "postgresql+psycopg://migration:secret@localhost:5432/inspector",
        "mcp_server_url": "http://localhost:8001/mcp",
        "model_api_key": "model-secret",
        "inspector_auth_secret": "c" * 32,
    }


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
