"""The experiment comparison report (feature 007).

Traces 007/FR-009, 007/FR-010, 007/FR-014, 007/SC-006, 007/SC-008.
"""
from kestrel.experiments import results
from kestrel.report.experiment import build_experiment_report, render_experiment_markdown
from kestrel.report.render import render_html
from kestrel.store import Experiment, ExperimentArm, Run

FEATURE = "007"

ARM_A = ExperimentArm(id=1, label="A", attacker_model="deepseek/deepseek-v4.1-flash",
                      judge_model="google/gemini-3.8-flash", use_prior_experience=False, turn_cap=6,
                      token_budget=40000, write_back=False, run_order=1)
ARM_B = ExperimentArm(id=2, label="B", attacker_model="qwen/qwen-3.5-max",
                      judge_model="google/gemini-3.8-flash", use_prior_experience=True, turn_cap=6,
                      token_budget=40000, write_back=True, run_order=2)
EXPERIMENT = Experiment(id=7, target_id=1, mode="adaptive", families=("direct_injection",), reps=3,
                        seed_prompt_ids={"direct_injection": "dir-001"}, max_runs=50, token_budget_total=500_000,
                        wall_clock_s=3600, status="finished", stopped_reason="completed", created_at="t",
                        started_at="t", finished_at="t", arms=(ARM_A, ARM_B))


def _run(**kw) -> Run:
    base = dict(id=1, target_id=1, prompt_id="dir-001", prompt_title="t", prompt_text="p",
                family="direct_injection", owasp_category="LLM01: Prompt Injection", attacker_source="s",
                status="finished", started_at="t", mode="adaptive")
    base.update(kw)
    return Run(**base)


def _model():
    ra = results.arm_result(ARM_A, [_run(verdict="succeeded", hard_evidence=True, tokens_used=1000)],
                            mode="adaptive", model_prices={})
    rb = results.arm_result(ARM_B, [_run(verdict="failed", tokens_used=2000)], mode="adaptive", model_prices={})
    comparison = results.build_comparison(ra, rb)
    return build_experiment_report(EXPERIMENT, ra, rb, comparison, diff=["retrieval: A=off, B=on"],
                                   order="A then B", warming="A cold (no write-back); B warm",
                                   now="2026-10-30T00:00:00Z", target_name="HS")


def test_report_names_both_attacker_models_and_judges():
    md = render_experiment_markdown(_model())
    assert "deepseek/deepseek-v4.1-flash" in md and "qwen/qwen-3.5-max" in md   # both attacker slugs (model+version)
    assert "google/gemini-3.8-flash" in md                                      # the judge model


def test_report_has_an_owasp_mapped_table():
    md = render_experiment_markdown(_model())
    assert "OWASP" in md and "LLM01: Prompt Injection" in md


def test_report_renders_markdown_and_html():
    md = render_experiment_markdown(_model())
    html = render_html(md)
    assert html.startswith("<!doctype html>") and "experiment" in html.lower()


def test_report_carries_the_small_sample_caveat():
    assert "sample" in render_experiment_markdown(_model()).lower()
