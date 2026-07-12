"""Store immutable, signed proposal package versions."""

import os

import sqlalchemy as sa
from alembic import op

revision = "0007_patch_package_versions"
down_revision = "0006_patch_decision_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patch_package_versions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("proposal_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("package_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["proposal_id"], ["patch_proposals.id"]),
        sa.UniqueConstraint("proposal_id", "version", name="uq_patch_package_proposal_version"),
    )
    role = os.environ.get("RUNTIME_DB_USER", "inspector_runtime").replace('"', '""')
    op.execute(f'GRANT SELECT, INSERT ON patch_package_versions TO "{role}"')


def downgrade() -> None:
    op.drop_table("patch_package_versions")
