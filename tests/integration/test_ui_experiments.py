"""The Experiments screen through AppTest, with api_client stubbed (feature 007). Traces 007/FR-013."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import api_client

FEATURE = "007"

APP = str(Path(__file__).resolve().parents[2] / "ui" / "app.py")
CONFIG = {"mode": "local",
          "defaults": {"method": "POST", "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"},
          "terms": {"version": "6", "text": "Terms text."},
          "judge": {"model": "google/gemini-3.8-flash", "configured": True},
          "attacker": {"model": "deepseek/deepseek-v4.1-flash", "configured": True}}
SUMMARY = {"id": 1, "name": "My agent", "url": "http://127.0.0.1:8001/chat", "method": "POST",
           "permission_confirmed_at": "2026-10-30T14:05:00Z", "terms_version": "6"}
DETAIL = {**SUMMARY, "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply",
          "headers": [], "canaries": []}
FAMILIES = {"library_version": "1.0.0",
            "families": [{"key": "direct_injection", "label": "Direct", "owasp_category": "LLM01: Prompt Injection",
                          "prompt_count": 5}]}


def _rate(rate, successes, n):
    return {"rate": rate, "successes": successes, "n": n, "ci": None if rate is None else [0.0, 0.5]}


def _arm(label):
    return {"label": label, "attacker_model": "m", "judge_model": "j", "run_order": 1 if label == "A" else 2,
            "completed": 3, "send_failures": 0, "confirmed": _rate(0.1, 0, 3), "suspected": _rate(0.3, 1, 3),
            "mean_turns_to_success": 2.0, "mean_tokens": 1200.0, "cost": 0.5, "cost_note": None,
            "by_family": [], "by_owasp": []}


RESULT = {"id": 1, "status": "finished", "stopped_reason": "completed", "mode": "adaptive",
          "families": ["direct_injection"], "reps": 3, "diff": ["retrieval: A=off, B=on"],
          "order": "A then B", "warming": "A cold (no write-back); B warm",
          "arms": [_arm("A"), _arm("B")],
          "comparison": {"confirmed": {"diff": 0.0, "small_sample": True, "caveat": "Small sample: indicative only."},
                         "suspected_diff": 0.0}}


@pytest.fixture
def api(monkeypatch):
    created = SimpleNamespace(payload=None)

    def create(payload):
        created.payload = payload
        return {"id": 1, "status": "running"}

    monkeypatch.setattr(api_client, "get_config", lambda: CONFIG)
    monkeypatch.setattr(api_client, "list_targets", lambda: [SUMMARY])
    monkeypatch.setattr(api_client, "get_target", lambda target_id: DETAIL)
    monkeypatch.setattr(api_client, "attack_families", lambda: FAMILIES)
    monkeypatch.setattr(api_client, "attack_prompts", lambda family: {"prompts": []})   # no real HTTP in the UI test
    monkeypatch.setattr(api_client, "list_runs", lambda target_id: [])
    monkeypatch.setattr(api_client, "get_profile", lambda target_id: {
        "target_id": 1, "total_runs": 0, "by_family": [], "by_verdict": [], "recent": []})
    monkeypatch.setattr(api_client, "create_experiment", create)
    monkeypatch.setattr(api_client, "experiment_status", lambda experiment_id: {
        "id": 1, "status": "finished", "stopped_reason": "completed", "planned_runs": 6, "completed_runs": 6,
        "tokens_used": 7200, "cost": 1.0, "arms": []})
    monkeypatch.setattr(api_client, "experiment_result", lambda experiment_id: RESULT)
    monkeypatch.setattr(api_client, "experiment_report", lambda experiment_id, fmt: "# report")
    return created


def test_experiments_section_and_arm_editors_render(api):
    at = AppTest.from_file(APP, default_timeout=10).run()
    assert any("Experiments" in s.value for s in at.subheader)
    assert at.text_input(key="arm_a_attacker").value == "deepseek/deepseek-v4.1-flash"
    assert at.text_input(key="arm_b_attacker").value == "deepseek/deepseek-v4.1-flash"


def test_start_sends_two_arms_and_shows_the_comparison(api):
    at = AppTest.from_file(APP, default_timeout=10).run()
    at.checkbox(key="arm_b_retrieval").set_value(True).run()
    at.button(key="exp_start").click().run()

    assert api.payload is not None
    assert "arm_a" in api.payload and "arm_b" in api.payload
    assert api.payload["arm_b"]["use_prior_experience"] is True
    # the finished comparison renders: a side-by-side table and the small-sample caveat
    assert any("Confirmed success" in str(frame.value) for frame in at.dataframe)
    assert any("Small sample" in w.value for w in at.warning)
