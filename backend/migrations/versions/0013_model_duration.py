"""Record model request duration for cost and execution audit."""

import sqlalchemy as sa
from alembic import op


revision = "0013_model_duration"
down_revision = "0012_model_cached_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_usage",
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.alter_column("model_usage", "duration_ms", server_default=None)


def downgrade() -> None:
    op.drop_column("model_usage", "duration_ms")
