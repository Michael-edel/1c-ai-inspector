"""Add cooperative task cancellation state."""

import sqlalchemy as sa
from alembic import op

revision = "0008_task_cancellation"
down_revision = "0007_patch_package_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("tasks", "cancel_requested", server_default=None)


def downgrade() -> None:
    op.drop_column("tasks", "cancel_requested")
