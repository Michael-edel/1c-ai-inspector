"""Backfill zero-cost GPT-5.5 usage with the public 2026-07-14 tariff."""

from alembic import op


revision = "0016_backfill_gpt55_costs"
down_revision = "0015_traffic_accounting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN cost_confirmed boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE tasks ADD COLUMN cost_estimate_usd double precision NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE tasks ADD COLUMN cost_estimate_kzt double precision NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE tasks ADD COLUMN cost_estimate_rate double precision NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE model_usage ADD COLUMN estimated_cost_kzt double precision NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE model_usage ADD COLUMN usd_kzt_rate double precision NOT NULL DEFAULT 0")
    op.execute(
        """
        UPDATE model_usage
        SET estimated_cost = ROUND((
                GREATEST(input_tokens - cached_input_tokens, 0) * 0.000005
                + cached_input_tokens * 0.0000005
                + output_tokens * 0.00003
            )::numeric, 8)::double precision,
            pricing_source = 'openai-public:gpt-5.5:2026-07-14'
        WHERE (model = 'gpt-5.5' OR model LIKE 'gpt-5.5-%')
          AND estimated_cost = 0
          AND input_tokens + output_tokens > 0
        """
    )
    op.execute(
        """
        UPDATE model_usage
        SET usd_kzt_rate = 464.71,
            estimated_cost_kzt = ROUND((estimated_cost * 464.71)::numeric, 4)::double precision
        WHERE estimated_cost > 0 AND estimated_cost_kzt = 0
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE model_usage DROP COLUMN usd_kzt_rate")
    op.execute("ALTER TABLE model_usage DROP COLUMN estimated_cost_kzt")
    op.execute("ALTER TABLE tasks DROP COLUMN cost_estimate_rate")
    op.execute("ALTER TABLE tasks DROP COLUMN cost_estimate_kzt")
    op.execute("ALTER TABLE tasks DROP COLUMN cost_estimate_usd")
    op.execute("ALTER TABLE tasks DROP COLUMN cost_confirmed")
