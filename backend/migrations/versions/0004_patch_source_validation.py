"""Add source snapshot validation state to Patch Planner proposals."""

import sqlalchemy as sa
from alembic import op

revision = "0004_patch_source_validation"
down_revision = "0003_patch_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "patch_proposals",
        sa.Column("source_validation_status", sa.String(length=32), nullable=False, server_default="unverified"),
    )
    op.add_column(
        "patch_proposals",
        sa.Column("source_validation_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.add_column("patch_proposals", sa.Column("source_validated_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("patch_proposals", "source_validated_at")
    op.drop_column("patch_proposals", "source_validation_json")
    op.drop_column("patch_proposals", "source_validation_status")
