"""The approve-node UI: the "Ask before each turn" checkbox (off by default, adaptive only), and a paused run's
pending message and its exactly three controls - Approve / Run to end / Stop - with the run's own `idle_stop_at`
shown beside them (014/FR-018, FR-020, FR-061).
"""
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import api_client

FEATURE = "014"

APP = str(Path(__file__).resolve().parents[2] / "ui" / "app.py")
CONFIG = {"mode": "local",
          "defaults": {"method": "POST", "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"},
          "terms": {"version": "2", "text": "Terms text."},
          "judge": {"model": "google/gemini-3.8-flash", "configured": True},
          "attacker": {"model": "deepseek/deepseek-v4.1-flash", "configured": True},
          "adaptive": {"max_turns": 6, "token_budget": 40000, "time_limit_s": 300},
          "experience": {"use_prior_experience_default": True}}
DETAIL = {"id": 1, "name": "My agent", "url": "http://127.0.0.1:8001/chat", "method": "POST",
          "permission_confirmed_at": "2026-10-23T14:05:00Z", "terms_version": "2",
          "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply", "headers": [], "canaries": []}
SUMMARY = {key: DETAIL[key] for key in ("id", "name", "url", "method", "permission_confirmed_at", "terms_version")}
FAMILIES = [{"key": "system_prompt_leak", "label": "System prompt leak",
            "owasp_category": "LLM07: System Prompt Leakage", "prompt_count": 5}]


def run(**over):
    base = {"id": 7, "target_id": 1, "prompt_id": "spl-002", "prompt_title": "Ask for the prompt",
            "family": "system_prompt_leak", "owasp_category": "LLM07: System Prompt Leakage", "status": "in_progress",
            "mode": "adaptive", "prompt_text": "<seed>", "reply_text": None, "reply_truncated": False,
            "verdict": None, "hard_evidence": False, "reason": None, "judge_used": False, "judge_model": None,
            "attacker_source": "library:1.0.0", "failure_step": None, "started_at": "2026-10-23T14:00:00Z",
            "finished_at": None, "source_run_id": None, "replay_outcome": None, "finding": False,
            "replayable": False, "replay_blocked_reason": "A run still in progress can't be replayed.",
            "replay_advisory": None, "comparison": None, "turns": [], "resumable": True, "paused": True,
            "run_state": "paused", "pending_turn": {"turn": 2, "interrupt_id": "abc", "message": "<drafted message>"},
            "idle_stop_at": "2026-10-24T14:00:00Z"}
    return {**base, **over}


@pytest.fixture
def api(monkeypatch):
    stub = SimpleNamespace(runs=[], decisions=[], decide_error=None)

    def decide_run(run_id, turn, decision):
        if stub.decide_error is not None:
            raise stub.decide_error
        stub.decisions.append((run_id, turn, decision))
        return {}

    monkeypatch.setattr(api_client, "get_config", lambda: CONFIG)
    monkeypatch.setattr(api_client, "list_targets", lambda: [SUMMARY])
    monkeypatch.setattr(api_client, "get_target", lambda target_id: DETAIL)
    monkeypatch.setattr(api_client, "attack_families", lambda: {"library_version": "1.0.0", "families": FAMILIES})
    monkeypatch.setattr(api_client, "attack_prompts", lambda family: {"prompts": []})
    monkeypatch.setattr(api_client, "get_profile", lambda target_id: {"target_id": 1, "total_runs": 0,
                                                                      "by_family": [], "by_verdict": [],
                                                                      "recent": []})
    monkeypatch.setattr(api_client, "list_runs", lambda target_id: stub.runs)
    monkeypatch.setattr(api_client, "get_run", lambda run_id: next(r for r in stub.runs if r["id"] == run_id))
    monkeypatch.setattr(api_client, "decide_run", decide_run)
    monkeypatch.setattr(api_client, "resume_run", lambda run_id: {})
    monkeypatch.setattr(api_client, "stop_run", lambda run_id: {})
    return stub


def loaded() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10).run()
    return at.selectbox(key="target_select").select(1).run()


def opened(api, the_run: dict) -> AppTest:
    api.runs = [the_run]
    at = loaded()
    return at.selectbox(key="open_run").select(the_run["id"]).run()


def test_the_checkbox_is_off_by_default_and_only_shown_for_adaptive(api):
    at = loaded()
    # Single-turn (the default): no checkbox at all.
    assert not any(k.key == "ask_before_each_turn" for k in at.checkbox)
    at = at.radio(key="attack_mode").set_value("Adaptive").run()
    box = next(k for k in at.checkbox if k.key == "ask_before_each_turn")
    assert box.value is False   # off by default


def test_a_paused_run_shows_the_pending_message_and_three_controls(api):
    at = opened(api, run())
    labels = [b.label for b in at.button if b.key]
    assert "Approve" in labels and "Run to end" in labels and "Stop" in labels
    # The pending message, verbatim, and the idle deadline, shown beside the controls.
    assert any(c.value == "<drafted message>" for c in at.code)
    assert any("2026-10-24" in c.value for c in at.caption)


def test_clicking_each_control_calls_the_matching_api_action_with_the_right_turn(api):
    at = opened(api, run())
    approve = next(b for b in at.button if b.key and b.key.startswith("approve_button_opened_7"))
    at.button(key=approve.key).click().run()
    assert api.decisions == [(7, 2, "approve")]

    api.decisions.clear()
    at = opened(api, run())
    run_to_end = next(b for b in at.button if b.key and b.key.startswith("run_to_end_button_opened_7"))
    at.button(key=run_to_end.key).click().run()
    assert api.decisions == [(7, 2, "run_to_end")]

    api.decisions.clear()
    at = opened(api, run())
    stop = next(b for b in at.button if b.key and b.key.startswith("decide_stop_button_opened_7"))
    at.button(key=stop.key).click().run()
    assert api.decisions == [(7, 2, "stop")]


def test_a_decision_error_is_shown_on_the_run_page(api):
    api.decide_error = api_client.ApiError(409, {"error": {"code": "not_paused", "field": None,
                                                           "message": "This run's pending turn has already moved on."}})
    at = opened(api, run())
    approve = next(b for b in at.button if b.key and b.key.startswith("approve_button_opened_7"))
    at = at.button(key=approve.key).click().run()
    assert any("pending turn has already moved on" in e.value for e in at.error)
