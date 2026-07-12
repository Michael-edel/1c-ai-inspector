from functools import lru_cache
from pathlib import Path

from typing import Literal

from pydantic import AnyHttpUrl, Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: PostgresDsn
    migration_database_url: PostgresDsn
    mcp_server_url: AnyHttpUrl
    mcp_transport: Literal["streamable-http", "bridge"] = "streamable-http"
    mcp_bridge_token: str | None = None
    mcp_projects_tool: str | None = None
    model_provider: str = "openai"
    model_name: str = "gpt-5.5"
    model_api_key: str = Field(min_length=1)
    model_api_url: AnyHttpUrl = "https://api.openai.com/v1"
    model_input_cost_per_1k: float = Field(default=0, ge=0)
    model_output_cost_per_1k: float = Field(default=0, ge=0)
    max_tool_calls: int = Field(default=30, ge=1, le=500)
    max_context_chars: int = Field(default=120_000, ge=1_000, le=2_000_000)
    task_timeout_sec: int = Field(default=300, ge=1, le=86_400)
    worker_lease_timeout_sec: int = Field(default=600, ge=5, le=86_400)
    mcp_policy_path: Path = Path("/app/mcp_policy.yaml")
    prompts_path: Path = Path("/app/prompts")
    app_environment: str = "sandbox"

    @field_validator("app_environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        if value not in {"sandbox", "test"}:
            raise ValueError("APP_ENVIRONMENT must be sandbox or test in v0.1")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
