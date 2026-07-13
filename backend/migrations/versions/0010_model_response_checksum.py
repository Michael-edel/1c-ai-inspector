"""Record model response checksums without retaining response content."""

import sqlalchemy as sa
from alembic import op


revision = "0010_model_response_checksum"
down_revision = "0009_tool_result_size"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_usage",
        sa.Column("response_checksum", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_usage", "response_checksum")
