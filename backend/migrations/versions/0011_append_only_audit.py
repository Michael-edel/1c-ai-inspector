"""Restrict runtime writes to append-only audit tables."""

import os

from alembic import op


revision = "0011_append_only_audit"
down_revision = "0010_model_response_checksum"
branch_labels = None
depends_on = None

AUDIT_TABLES = (
    "task_events",
    "tool_calls",
    "findings",
    "finding_status_events",
    "model_usage",
    "prompt_execution_snapshots",
)


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def upgrade() -> None:
    runtime_role = _quoted_identifier(os.environ.get("RUNTIME_DB_USER", "inspector_runtime"))
    migration_role = _quoted_identifier(os.environ.get("MIGRATION_DB_USER", "inspector_migration"))
    for table in AUDIT_TABLES:
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM {runtime_role}")
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE "
        f"{migration_role} IN SCHEMA public REVOKE UPDATE, DELETE ON TABLES FROM {runtime_role}"
    )


def downgrade() -> None:
    runtime_role = _quoted_identifier(os.environ.get("RUNTIME_DB_USER", "inspector_runtime"))
    migration_role = _quoted_identifier(os.environ.get("MIGRATION_DB_USER", "inspector_migration"))
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE "
        f"{migration_role} IN SCHEMA public GRANT UPDATE, DELETE ON TABLES TO {runtime_role}"
    )
    for table in AUDIT_TABLES:
        op.execute(f"GRANT UPDATE, DELETE ON {table} TO {runtime_role}")
