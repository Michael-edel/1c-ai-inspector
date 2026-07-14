"""Create the v0.1 foundation schema."""

import os

from alembic import op

from app.models import Base

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None

FOUNDATION_TABLES = (
    "mcp_servers",
    "projects",
    "agents",
    "tasks",
    "task_events",
    "tool_calls",
    "findings",
    "finding_status_events",
    "normalized_tools",
    "model_usage",
    "prompt_execution_snapshots",
)

# Base.metadata reflects the current application model. Keep the foundation
# revision historical so later column migrations remain valid on a clean DB.
DEFERRED_COLUMNS = (
    ("tasks", "cancel_requested"),
    ("tool_calls", "result_size_chars"),
    ("tool_calls", "request_size_bytes"),
    ("tool_calls", "result_size_bytes"),
    ("model_usage", "response_checksum"),
    ("model_usage", "cached_input_tokens"),
    ("model_usage", "pricing_source"),
    ("model_usage", "duration_ms"),
    ("model_usage", "request_size_bytes"),
    ("model_usage", "response_size_bytes"),
)


def upgrade() -> None:
    bind = op.get_bind()
    tables = [Base.metadata.tables[name] for name in FOUNDATION_TABLES]
    Base.metadata.create_all(bind=bind, tables=tables)
    for table_name, column_name in DEFERRED_COLUMNS:
        op.drop_column(table_name, column_name)
    runtime_role = os.environ.get("RUNTIME_DB_USER", "inspector_runtime")
    quoted_role = '"' + runtime_role.replace('"', '""') + '"'
    op.execute(f"GRANT USAGE ON SCHEMA public TO {quoted_role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON projects, mcp_servers, agents, tasks TO {quoted_role}")
    op.execute(f"GRANT SELECT, INSERT ON task_events, tool_calls, findings, finding_status_events TO {quoted_role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON normalized_tools, model_usage, prompt_execution_snapshots TO {quoted_role}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {quoted_role}")


def downgrade() -> None:
    bind = op.get_bind()
    tables = [Base.metadata.tables[name] for name in FOUNDATION_TABLES]
    Base.metadata.drop_all(bind=bind, tables=tables)
