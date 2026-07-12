"""Add Patch Planner audit events."""

import os

import sqlalchemy as sa
from alembic import op

revision = "0003_patch_events"
down_revision = "0002_patch_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patch_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("proposal_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["proposal_id"], ["patch_proposals.id"]),
    )
    role = os.environ.get("RUNTIME_DB_USER", "inspector_runtime").replace('"', '""')
    op.execute(f'GRANT SELECT, INSERT ON patch_events TO "{role}"')


def downgrade() -> None:
    op.drop_table("patch_events")
