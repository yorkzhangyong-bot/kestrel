"""A model request's estimated cost: the feature-007 price table and arithmetic; null with a reason, never zero
(010/FR-008, 010/SC-006)."""
import math

import pytest

from kestrel import events
from kestrel.experiments.pricing import arm_cost

FEATURE = "010"

PRICES = {"m": 0.0015, "cheap": 0.00006}


def test_a_priced_request_costs_tokens_over_1000_times_the_price():  # FR-008, SC-006
    cost, note = events.request_cost(908, "m", PRICES)
    assert math.isclose(cost, 908 / 1000 * 0.0015, abs_tol=1e-9) and note is None
    assert math.isclose(cost, arm_cost(908, "m", PRICES), abs_tol=1e-9)   # the experiment harness's arithmetic


def test_an_unpriced_model_is_null_with_the_feature_007_wording_never_zero():  # FR-008, SC-006
    cost, note = events.request_cost(908, "unpriced/model", PRICES)
    assert cost is None and cost != 0.0
    assert note == "unavailable (no configured price for unpriced/model)"


def test_no_reported_usage_is_null_with_its_own_reason():  # FR-008, SC-006
    assert events.request_cost(None, "m", PRICES) == (None, "no usage reported by the provider")


def _context_with(requests):
    """A live run context that accumulated the given (total_tokens, model) requests on one turn."""
    events.configure(prices=PRICES)
    with events.run_scope() as ctx:
        events.run_started(None, run_id=1, target_id=1, mode="adaptive", family="direct_injection")
        events.turn_started(1)
        for total, model in requests:
            events.model_request(kind="judge", model=model, prompt="judge@1", latency_ms=1, ok=True, status=200,
                                 attempts=1, prompt_tokens=None, completion_tokens=None, total_tokens=total,
                                 verdict="failed")
        turn = ctx.turn_cost.value()
        run = ctx.run_cost.value()
    return turn, run


def test_the_turn_and_run_totals_sum_priced_requests():  # FR-008, SC-006
    turn, run = _context_with([(1000, "m"), (2000, "cheap")])
    expected = 1000 / 1000 * 0.0015 + 2000 / 1000 * 0.00006
    assert math.isclose(turn[0], expected, abs_tol=1e-9) and turn[1] is None
    assert math.isclose(run[0], expected, abs_tol=1e-9) and run[1] is None


@pytest.mark.parametrize("requests, reason", [
    ([(1000, "m"), (500, "unpriced/model")], "unavailable (no configured price for unpriced/model)"),
    ([(None, "m"), (500, "unpriced/model")], "no usage reported by the provider"),
])
def test_a_total_is_null_with_the_first_reason_when_any_request_is_unpriced(requests, reason):  # FR-008, SC-006
    turn, run = _context_with(requests)
    assert turn == (None, reason) and run == (None, reason)


def test_a_turn_without_any_model_request_costs_zero():  # FR-008 (nothing was spent)
    turn, run = _context_with([])
    assert turn == (0.0, None) and run == (0.0, None)
