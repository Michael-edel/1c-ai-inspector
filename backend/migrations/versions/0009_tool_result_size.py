"""Record MCP result size without retaining oversized output."""

import sqlalchemy as sa
from alembic import op


revision = "0009_tool_result_size"
down_revision = "0008_task_cancellation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tool_calls", sa.Column("result_size_chars", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("tool_calls", "result_size_chars")
