"""Add explicit Patch Planner decision roles."""

import sqlalchemy as sa
from alembic import op

revision = "0006_patch_decision_roles"
down_revision = "0005_patch_validation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patch_proposals", sa.Column("decision_role", sa.String(length=32)))


def downgrade() -> None:
    op.drop_column("patch_proposals", "decision_role")
