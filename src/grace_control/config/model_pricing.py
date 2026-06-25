"""Model pricing definitions and cost computation helper."""
from __future__ import annotations

MODEL_PRICING = {
    # USD per 1M tokens (in, out)
    "deepseek/deepseek-v4-flash":      {"in": 0.14, "out": 0.28},
    "deepseek/deepseek-v4-pro":        {"in": 0.55, "out": 1.10},
    "anthropic/claude-sonnet-4-5":     {"in": 3.00, "out": 15.00},
    "anthropic/claude-opus-4-1":       {"in": 15.00, "out": 75.00},
    "openai/gpt-4o":                   {"in": 2.50, "out": 10.00},
    "openai/gpt-4o-mini":              {"in": 0.15, "out": 0.60},
}


def compute_cost(model: str | None, tokens_in: int | None, tokens_out: int | None) -> float:
    if not model or tokens_in is None or tokens_out is None:
        return 0.0
    pricing = MODEL_PRICING.get(model, {"in": 0.0, "out": 0.0})
    return (tokens_in / 1_000_000.0) * pricing["in"] + \
           (tokens_out / 1_000_000.0) * pricing["out"]
