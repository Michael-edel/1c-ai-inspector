"""Create the v0.1 foundation schema."""

import os

from alembic import op

from app.models import Base

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    runtime_role = os.environ.get("RUNTIME_DB_USER", "inspector_runtime")
    quoted_role = '"' + runtime_role.replace('"', '""') + '"'
    op.execute(f"GRANT USAGE ON SCHEMA public TO {quoted_role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON projects, mcp_servers, agents, tasks TO {quoted_role}")
    op.execute(f"GRANT SELECT, INSERT ON task_events, tool_calls, findings, finding_status_events TO {quoted_role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON normalized_tools, model_usage, prompt_execution_snapshots TO {quoted_role}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {quoted_role}")


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
