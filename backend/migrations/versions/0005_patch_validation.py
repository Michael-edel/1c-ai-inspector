"""Add deterministic Patch Planner validation state."""

import sqlalchemy as sa
from alembic import op

revision = "0005_patch_validation"
down_revision = "0004_patch_source_validation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "patch_proposals",
        sa.Column("validation_status", sa.String(length=32), nullable=False, server_default="unvalidated"),
    )
    op.add_column(
        "patch_proposals",
        sa.Column("validation_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.add_column("patch_proposals", sa.Column("validated_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("patch_proposals", "validated_at")
    op.drop_column("patch_proposals", "validation_json")
    op.drop_column("patch_proposals", "validation_status")
