"""Add feature-flagged Sandbox Executor state and audit storage."""

import os

import sqlalchemy as sa
from alembic import op


revision = "0014_sandbox_executions"
down_revision = "0013_model_duration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sandbox_executions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("proposal_id", sa.String(length=64), nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_commit", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("branch_name", sa.String(length=255)),
        sa.Column("worktree_path", sa.Text()),
        sa.Column("validation_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("test_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("last_error_code", sa.String(length=100)),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["proposal_id"], ["patch_proposals.id"]),
    )
    op.create_table(
        "sandbox_execution_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["execution_id"], ["sandbox_executions.id"]),
    )
    role = os.environ.get("RUNTIME_DB_USER", "inspector_runtime").replace('"', '""')
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON sandbox_executions TO "{role}"')
    op.execute(f'GRANT SELECT, INSERT ON sandbox_execution_events TO "{role}"')
    op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')


def downgrade() -> None:
    op.drop_table("sandbox_execution_events")
    op.drop_table("sandbox_executions")
