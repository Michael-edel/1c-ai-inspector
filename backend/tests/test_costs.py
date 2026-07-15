from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, ModelUsage
from app.services.costs import (
    convert_usd_to_kzt,
    estimate_cost,
    model_cost_snapshot,
    model_request_cost_estimate,
    resolve_model_pricing,
    round_kzt,
)


def test_estimate_cost() -> None:
    assert estimate_cost(1500, 500, 0.2, 0.4) == 0.5


def test_negative_cost_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        estimate_cost(-1, 0, 0, 0)


def test_kzt_amounts_use_financial_whole_tenge_rounding() -> None:
    assert round_kzt(10.49) == 10
    assert round_kzt(10.5) == 11
    assert convert_usd_to_kzt(0.105, 100) == 11


def test_estimate_cost_separates_cached_input_tokens() -> None:
    assert estimate_cost(
        1000,
        500,
        0.005,
        0.03,
        cached_input_tokens=400,
        cached_input_cost_per_1k=0.0005,
    ) == 0.0182


def test_official_gpt55_pricing_and_kzt_upper_bound() -> None:
    settings = SimpleNamespace(
        model_name="gpt-5.5",
        model_input_cost_per_1k=None,
        model_cached_input_cost_per_1k=None,
        model_output_cost_per_1k=None,
        max_context_chars=120_000,
        model_input_token_estimate_chars=3,
        model_prompt_overhead_tokens=4_000,
        model_max_output_tokens=16_384,
        usd_kzt_rate=464.71,
        usd_kzt_rate_date="2026-07-14",
        usd_kzt_rate_source="nationalbank.kz",
    )

    pricing = resolve_model_pricing(settings)  # type: ignore[arg-type]
    estimate = model_request_cost_estimate(settings)  # type: ignore[arg-type]

    assert pricing.input_cost_per_1k == 0.005
    assert pricing.cached_input_cost_per_1k == 0.0005
    assert pricing.output_cost_per_1k == 0.03
    assert estimate["inputTokens"] == 44_000
    assert estimate["estimatedCostKzt"] == convert_usd_to_kzt(
        float(estimate["estimatedCostUsd"]), 464.71
    )


def test_official_gpt56_luna_pricing_and_kzt_upper_bound() -> None:
    settings = SimpleNamespace(
        model_name="gpt-5.6-luna",
        model_input_cost_per_1k=None,
        model_cached_input_cost_per_1k=None,
        model_output_cost_per_1k=None,
        max_context_chars=120_000,
        model_input_token_estimate_chars=3,
        model_prompt_overhead_tokens=4_000,
        model_max_output_tokens=16_384,
        usd_kzt_rate=464.71,
        usd_kzt_rate_date="2026-07-14",
        usd_kzt_rate_source="nationalbank.kz",
    )

    pricing = resolve_model_pricing(settings)  # type: ignore[arg-type]
    estimate = model_request_cost_estimate(settings)  # type: ignore[arg-type]

    assert pricing.input_cost_per_1k == 0.001
    assert pricing.cached_input_cost_per_1k == 0.0001
    assert pricing.output_cost_per_1k == 0.006
    assert pricing.source == "openai-public:gpt-5.6-luna:2026-07-14"
    assert estimate["inputTokens"] == 44_000
    assert estimate["estimatedCostUsd"] == 0.142304
    assert estimate["estimatedCostKzt"] == 66


def test_incomplete_environment_pricing_is_rejected() -> None:
    settings = SimpleNamespace(
        model_name="gpt-5.5",
        model_input_cost_per_1k=0.005,
        model_cached_input_cost_per_1k=None,
        model_output_cost_per_1k=0.03,
    )
    with pytest.raises(ValueError, match="MODEL_PRICING_OVERRIDE_INCOMPLETE"):
        resolve_model_pricing(settings)  # type: ignore[arg-type]


def test_monthly_cost_snapshot_reports_kzt_and_token_totals() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = SimpleNamespace(
        model_name="gpt-5.5",
        model_input_cost_per_1k=None,
        model_cached_input_cost_per_1k=None,
        model_output_cost_per_1k=None,
        usd_kzt_rate=464.71,
        usd_kzt_rate_date="2026-07-14",
        usd_kzt_rate_source="nationalbank.kz",
    )
    with Session(engine) as session:
        session.add(
            ModelUsage(
                task_id="tsk_cost",
                provider="openai",
                model="gpt-5.5",
                input_tokens=1000,
                cached_input_tokens=400,
                output_tokens=500,
                estimated_cost=0.0182,
                estimated_cost_kzt=8.4577,
                usd_kzt_rate=464.71,
                pricing_source="openai-public:gpt-5.5:2026-07-14",
            )
        )
        session.commit()

        snapshot = model_cost_snapshot(session, settings)  # type: ignore[arg-type]

    assert snapshot["currency"] == "KZT"
    assert snapshot["calls"] == 1
    assert snapshot["inputTokens"] == 1000
    assert snapshot["cachedInputTokens"] == 400
    assert snapshot["outputTokens"] == 500
    assert snapshot["estimatedCostKzt"] == 8
