import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("MIGRATION_DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("MCP_SERVER_URL", "http://localhost:8001/mcp")
os.environ.setdefault("MODEL_API_KEY", "test-key")
os.environ.setdefault("MODEL_NAME", "gpt-5.6-luna")
os.environ.setdefault("MCP_POLICY_PATH", str(ROOT / "mcp_policy.yaml"))
os.environ.setdefault("APP_ENVIRONMENT", "test")
