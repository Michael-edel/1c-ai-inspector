"""Add proposal-only Patch Planner storage."""

import sqlalchemy as sa
from alembic import op

revision = "0002_patch_proposals"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patch_proposals",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("target_environment", sa.String(length=32), nullable=False),
        sa.Column("source_revision", sa.String(length=128), nullable=True),
        sa.Column("diff_text", sa.Text(), nullable=True),
        sa.Column("files_json", sa.Text(), nullable=False),
        sa.Column("impact_json", sa.Text(), nullable=False),
        sa.Column("checkpoint_ref", sa.String(length=255), nullable=True),
        sa.Column("approval_note", sa.Text(), nullable=True),
        sa.Column("approved_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
    )
    runtime_role = sa.sql.quoted_name(__import__("os").environ.get("RUNTIME_DB_USER", "inspector_runtime"), quote=True)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON patch_proposals TO {runtime_role}")


def downgrade() -> None:
    op.drop_table("patch_proposals")
