"""Add fail-closed monthly traffic accounting."""

import os

import sqlalchemy as sa
from alembic import op


revision = "0015_traffic_accounting"
down_revision = "0014_sandbox_executions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tool_calls", sa.Column("request_size_bytes", sa.BigInteger()))
    op.add_column("tool_calls", sa.Column("result_size_bytes", sa.BigInteger()))
    op.add_column(
        "model_usage",
        sa.Column("request_size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "model_usage",
        sa.Column("response_size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_table(
        "traffic_usage",
        sa.Column("period", sa.String(length=7), primary_key=True),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("reserved_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    role = os.environ.get("RUNTIME_DB_USER", "inspector_runtime").replace('"', '""')
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON traffic_usage TO "{role}"')


def downgrade() -> None:
    op.drop_table("traffic_usage")
    op.drop_column("model_usage", "response_size_bytes")
    op.drop_column("model_usage", "request_size_bytes")
    op.drop_column("tool_calls", "result_size_bytes")
    op.drop_column("tool_calls", "request_size_bytes")
