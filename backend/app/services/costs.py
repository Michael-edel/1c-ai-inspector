from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import ModelUsage


@dataclass(frozen=True)
class ModelPricing:
    model: str
    input_cost_per_1k: float
    cached_input_cost_per_1k: float
    output_cost_per_1k: float
    source: str


OFFICIAL_MODEL_PRICING = {
    "gpt-5.5": ModelPricing(
        model="gpt-5.5",
        input_cost_per_1k=0.005,
        cached_input_cost_per_1k=0.0005,
        output_cost_per_1k=0.03,
        source="openai-public:gpt-5.5:2026-07-14",
    ),
}


def resolve_model_pricing(settings: Settings) -> ModelPricing:
    overrides = (
        getattr(settings, "model_input_cost_per_1k", None),
        getattr(settings, "model_cached_input_cost_per_1k", None),
        getattr(settings, "model_output_cost_per_1k", None),
    )
    if any(value is not None and value > 0 for value in overrides):
        if any(value is None or value <= 0 for value in overrides):
            raise ValueError("MODEL_PRICING_OVERRIDE_INCOMPLETE")
        return ModelPricing(
            model=settings.model_name,
            input_cost_per_1k=float(overrides[0]),
            cached_input_cost_per_1k=float(overrides[1]),
            output_cost_per_1k=float(overrides[2]),
            source="environment",
        )
    model_key = (
        "gpt-5.5"
        if settings.model_name == "gpt-5.5" or settings.model_name.startswith("gpt-5.5-")
        else settings.model_name
    )
    try:
        return OFFICIAL_MODEL_PRICING[model_key]
    except KeyError as exc:
        raise ValueError("MODEL_PRICING_NOT_CONFIGURED") from exc


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    input_cost_per_1k: float,
    output_cost_per_1k: float,
    *,
    cached_input_tokens: int = 0,
    cached_input_cost_per_1k: float | None = None,
) -> float:
    cached_price = input_cost_per_1k if cached_input_cost_per_1k is None else cached_input_cost_per_1k
    if min(
        input_tokens,
        output_tokens,
        cached_input_tokens,
        input_cost_per_1k,
        output_cost_per_1k,
        cached_price,
    ) < 0:
        raise ValueError("tokens and prices cannot be negative")
    if cached_input_tokens > input_tokens:
        raise ValueError("cached input tokens cannot exceed input tokens")
    uncached_input_tokens = input_tokens - cached_input_tokens
    return round(
        (uncached_input_tokens / 1000 * input_cost_per_1k)
        + (cached_input_tokens / 1000 * cached_price)
        + (output_tokens / 1000 * output_cost_per_1k),
        8,
    )


def convert_usd_to_kzt(cost_usd: float, rate: float) -> float:
    if min(cost_usd, rate) < 0:
        raise ValueError("cost and exchange rate cannot be negative")
    return round(cost_usd * rate, 4)


def model_request_cost_estimate(settings: Settings) -> dict[str, object]:
    pricing = resolve_model_pricing(settings)
    input_tokens = (
        ceil(getattr(settings, "max_context_chars", 120_000) / getattr(settings, "model_input_token_estimate_chars", 3.0))
        + getattr(settings, "model_prompt_overhead_tokens", 4_000)
    )
    output_tokens = getattr(settings, "model_max_output_tokens", 16_384)
    cost_usd = estimate_cost(
        input_tokens,
        output_tokens,
        pricing.input_cost_per_1k,
        pricing.output_cost_per_1k,
    )
    return {
        "currency": "KZT",
        "estimateType": "upper-bound",
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "estimatedCostUsd": cost_usd,
        "estimatedCostKzt": convert_usd_to_kzt(cost_usd, getattr(settings, "usd_kzt_rate", 464.71)),
        "usdKztRate": getattr(settings, "usd_kzt_rate", 464.71),
        "rateDate": getattr(settings, "usd_kzt_rate_date", "2026-07-14"),
        "rateSource": getattr(settings, "usd_kzt_rate_source", "nationalbank.kz"),
        "pricingSource": pricing.source,
        "model": pricing.model,
    }


def model_cost_snapshot(db: Session, settings: Settings) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    period_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    pricing = resolve_model_pricing(settings)
    row = db.execute(
        select(
            func.count(ModelUsage.id),
            func.coalesce(func.sum(ModelUsage.input_tokens), 0),
            func.coalesce(func.sum(ModelUsage.cached_input_tokens), 0),
            func.coalesce(func.sum(ModelUsage.output_tokens), 0),
            func.coalesce(func.sum(ModelUsage.estimated_cost), 0.0),
            func.coalesce(func.sum(ModelUsage.estimated_cost_kzt), 0.0),
        ).where(ModelUsage.created_at >= period_start)
    ).one()
    return {
        "period": period_start.strftime("%Y-%m"),
        "currency": "KZT",
        "calls": int(row[0]),
        "inputTokens": int(row[1]),
        "cachedInputTokens": int(row[2]),
        "outputTokens": int(row[3]),
        "estimatedCost": round(float(row[4]), 8),
        "estimatedCostUsd": round(float(row[4]), 8),
        "estimatedCostKzt": round(float(row[5]), 4),
        "usdKztRate": settings.usd_kzt_rate,
        "rateDate": settings.usd_kzt_rate_date,
        "rateSource": settings.usd_kzt_rate_source,
        "pricing": {
            "model": pricing.model,
            "inputPer1M": pricing.input_cost_per_1k * 1000,
            "cachedInputPer1M": pricing.cached_input_cost_per_1k * 1000,
            "outputPer1M": pricing.output_cost_per_1k * 1000,
            "source": pricing.source,
        },
    }
