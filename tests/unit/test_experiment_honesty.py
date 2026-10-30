"""Honest statistics (feature 007): confirmed vs suspected never conflated; no bare % at small N.

Traces 007/FR-006, 007/FR-007, 007/SC-002, 007/SC-003. These guarantees live in experiments.results; this locks them.
"""
from kestrel.experiments import results
from kestrel.store import ExperimentArm, Run

FEATURE = "007"

ARM = ExperimentArm(id=1, label="A", attacker_model="m", judge_model="j", use_prior_experience=True,
                    turn_cap=6, token_budget=40000, write_back=True, run_order=1)


def _run(**kw) -> Run:
    base = dict(id=1, target_id=1, prompt_id="dir-001", prompt_title="t", prompt_text="p",
                family="direct_injection", owasp_category="LLM01: Prompt Injection", attacker_source="s",
                status="finished", started_at="2026-01-01T00:00:00Z", mode="adaptive")
    base.update(kw)
    return Run(**base)


def test_confirmed_and_suspected_are_separate_never_one_number():
    runs = [_run(verdict="succeeded", hard_evidence=True, tokens_used=1),    # confirmed only
            _run(verdict="succeeded", hard_evidence=False, tokens_used=1)]   # suspected only
    r = results.arm_result(ARM, runs, mode="adaptive", model_prices={})
    assert r.confirmed.successes == 1 and r.suspected.successes == 1   # counted once each, never conflated
    assert hasattr(r, "confirmed") and hasattr(r, "suspected")
    assert not hasattr(r, "success_rate")


def test_small_sample_comparison_carries_an_indicator_and_caveat():
    a = results.arm_result(ARM, [_run(verdict="failed", tokens_used=1)], mode="adaptive", model_prices={})
    b = results.arm_result(ARM, [_run(verdict="succeeded", hard_evidence=True, tokens_used=1)],
                           mode="adaptive", model_prices={})
    comp = results.build_comparison(a, b)
    assert "significant" in comp.confirmed and comp.confirmed["small_sample"] is True
    assert comp.confirmed["caveat"]   # never a bare percentage at small N


def test_zero_scored_runs_is_no_data_not_zero_percent():
    r = results.arm_result(ARM, [], mode="adaptive", model_prices={})
    assert r.confirmed.rate is None and r.suspected.rate is None   # "no data", not 0%


def test_a_failed_send_is_excluded_from_the_rate_denominator():
    # A run that could not send has no verdict; it must not count as a failure in the rate.
    runs = [_run(verdict="succeeded", hard_evidence=True, tokens_used=1),
            _run(verdict=None, failure_step="send", tokens_used=0)]
    r = results.arm_result(ARM, runs, mode="adaptive", model_prices={})
    assert r.confirmed.n == 1 and r.confirmed.successes == 1   # the unsent run is not in n
