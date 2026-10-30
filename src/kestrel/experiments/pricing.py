"""Estimated cost from tokens and a configured per-model price (feature 007, FR-006).

cost = tokens / 1000 * price[price_model]. The price_model is the arm's primary model: the attacker model for an
adaptive arm, the judge model for a single-turn arm (the model that consumed the run's tokens). Cost is None -
rendered "unavailable" - when that model has no configured price (no live billing lookup; research R3).
"""
from __future__ import annotations

from typing import Mapping


def arm_cost(total_tokens: int, price_model: str, model_prices: Mapping[str, float]) -> float | None:
    """Estimated USD cost for ``total_tokens`` priced at ``price_model``, or None if its price is unconfigured."""
    price = model_prices.get(price_model)
    if price is None:
        return None
    return total_tokens / 1000.0 * price
