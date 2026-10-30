"""Estimated cost = tokens x configured per-model price (feature 007). Traces 007/FR-006."""
from kestrel.experiments import pricing

FEATURE = "007"

PRICES = {"deepseek/deepseek-v4.1-flash": 0.30, "google/gemini-3.8-flash": 0.20}


def test_cost_for_a_priced_model():
    assert pricing.arm_cost(10_000, "deepseek/deepseek-v4.1-flash", PRICES) == 3.0


def test_cost_unavailable_when_price_unset():
    assert pricing.arm_cost(10_000, "unpriced/model", PRICES) is None


def test_zero_tokens_is_zero_cost():
    assert pricing.arm_cost(0, "google/gemini-3.8-flash", PRICES) == 0.0
