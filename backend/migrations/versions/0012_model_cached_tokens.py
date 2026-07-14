"""Record cached model input tokens and pricing source."""

import sqlalchemy as sa
from alembic import op


revision = "0012_model_cached_tokens"
down_revision = "0011_append_only_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_usage",
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "model_usage",
        sa.Column("pricing_source", sa.String(length=128), nullable=False, server_default="environment"),
    )
    op.alter_column("model_usage", "cached_input_tokens", server_default=None)
    op.alter_column("model_usage", "pricing_source", server_default=None)


def downgrade() -> None:
    op.drop_column("model_usage", "pricing_source")
    op.drop_column("model_usage", "cached_input_tokens")
