"""Per-arm result aggregation + comparison (feature 007). Traces 007/FR-006, 007/FR-007."""
from kestrel.experiments import results
from kestrel.store import ExperimentArm, Run

FEATURE = "007"

ARM = ExperimentArm(id=1, label="A", attacker_model="m-a", judge_model="j", use_prior_experience=True,
                    turn_cap=6, token_budget=40000, write_back=True, run_order=1)
PRICES = {"m-a": 0.5}


def _run(**kw) -> Run:
    base = dict(id=1, target_id=1, prompt_id="dir-001", prompt_title="t", prompt_text="p",
                family="direct_injection", owasp_category="LLM01: Prompt Injection", attacker_source="s",
                status="finished", started_at="2026-01-01T00:00:00Z", mode="adaptive", attacker_model="m-a",
                judge_model="j")
    base.update(kw)
    return Run(**base)


def test_arm_result_splits_confirmed_and_suspected():
    runs = [_run(verdict="succeeded", hard_evidence=True, tokens_used=1000, succeeded_turn=2),
            _run(verdict="succeeded", hard_evidence=False, tokens_used=2000, succeeded_turn=3),
            _run(verdict="failed", hard_evidence=False, tokens_used=500)]
    r = results.arm_result(ARM, runs, mode="adaptive", model_prices=PRICES)
    assert r.confirmed.successes == 1 and r.confirmed.n == 3
    assert r.suspected.successes == 1 and r.suspected.n == 3
    assert r.confirmed.ci is not None
    assert r.mean_tokens == (1000 + 2000 + 500) / 3
    assert r.cost == 3500 / 1000 * 0.5   # priced at the attacker model (adaptive arm)
    assert round(r.mean_turns_to_success, 1) == 2.5


def test_cost_unavailable_without_a_configured_price():
    r = results.arm_result(ARM, [_run(verdict="failed", tokens_used=100)], mode="adaptive", model_prices={})
    assert r.cost is None and r.cost_note


def test_by_family_and_owasp_breakdowns():
    runs = [_run(verdict="succeeded", hard_evidence=True, tokens_used=1),
            _run(family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                 verdict="failed", tokens_used=1)]
    r = results.arm_result(ARM, runs, mode="adaptive", model_prices=PRICES)
    assert {c.key for c in r.by_family} == {"direct_injection", "system_prompt_leak"}
    assert {c.key for c in r.by_owasp} == {"LLM01: Prompt Injection", "LLM07: System Prompt Leakage"}


def test_no_data_when_no_scored_runs():
    r = results.arm_result(ARM, [], mode="adaptive", model_prices=PRICES)
    assert r.confirmed.rate is None and r.confirmed.ci is None


def test_build_comparison_tests_the_confirmed_rate_with_caveat():
    a = results.arm_result(ARM, [_run(verdict="failed", tokens_used=1)] * 5
                           + [_run(verdict="succeeded", hard_evidence=True, tokens_used=1)],
                           mode="adaptive", model_prices=PRICES)
    b = results.arm_result(ARM, [_run(verdict="succeeded", hard_evidence=True, tokens_used=1)] * 4
                           + [_run(verdict="failed", tokens_used=1)] * 2,
                           mode="adaptive", model_prices=PRICES)
    comp = results.build_comparison(a, b)
    assert comp.confirmed["diff"] is not None
    assert comp.confirmed["small_sample"] is True and comp.confirmed["caveat"]
