def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    input_cost_per_1k: float,
    output_cost_per_1k: float,
) -> float:
    if min(input_tokens, output_tokens, input_cost_per_1k, output_cost_per_1k) < 0:
        raise ValueError("tokens and prices cannot be negative")
    return round(
        (input_tokens / 1000 * input_cost_per_1k)
        + (output_tokens / 1000 * output_cost_per_1k),
        8,
    )
