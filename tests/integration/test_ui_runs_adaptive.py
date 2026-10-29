"""The Runs table Mode column and opening an adaptive run from it (contracts/ui-screen.md, FR-022, FR-023)."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import api_client

FEATURE = "003"

APP = str(Path(__file__).resolve().parents[2] / "ui" / "app.py")
CONFIG = {"mode": "local",
          "defaults": {"method": "POST", "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"},
          "terms": {"version": "3", "text": "Terms."},
          "judge": {"model": "google/gemini-3.8-flash", "configured": True},
          "attacker": {"model": "deepseek/deepseek-v3.2", "configured": True},
          "adaptive": {"max_turns": 6, "token_budget": 40000, "time_limit_s": 300}}
DETAIL = {"id": 1, "name": "My agent", "url": "http://127.0.0.1:8001/chat", "method": "POST",
          "permission_confirmed_at": "2026-10-24T14:05:00Z", "terms_version": "3",
          "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply", "headers": [], "canaries": []}
SUMMARY = {k: DETAIL[k] for k in ("id", "name", "url", "method", "permission_confirmed_at", "terms_version")}

SINGLE = {"id": 5, "target_id": 1, "mode": "single_turn", "prompt_id": "dir-001", "prompt_title": "single one",
          "family": "direct_injection", "owasp_category": "LLM01: Prompt Injection", "verdict": "failed",
          "hard_evidence": False, "judge_used": True, "judge_model": "google/gemini-3.8-flash", "failure_step": None,
          "started_at": "2026-10-24T13:00:00Z", "finished_at": "2026-10-24T13:00:05Z"}
ADAPTIVE = {"id": 6, "target_id": 1, "mode": "adaptive", "prompt_id": "spl-002", "prompt_title": "adaptive one",
            "family": "system_prompt_leak", "owasp_category": "LLM07: System Prompt Leakage", "verdict": "failed",
            "hard_evidence": False, "judge_used": True, "judge_model": "google/gemini-3.8-flash", "failure_step": None,
            "started_at": "2026-10-24T14:00:00Z", "finished_at": "2026-10-24T14:00:30Z"}
ADAPTIVE_DETAIL = {**ADAPTIVE, "status": "finished", "prompt_text": "<seed>", "reply_text": None,
                   "reply_truncated": False, "reason": "held", "attacker_source": "library:1.0.0",
                   "attacker_model": "deepseek/deepseek-v3.2", "turn_budget": 6, "turns_used": 2,
                   "token_budget": 40000, "tokens_used": 1500, "time_limit_s": 300, "stopping_condition": "turn_cap",
                   "succeeded_turn": None,
                   "turns": [{"position": 1, "attacker_message": "<m1>", "reply_text": "<r1>", "reply_truncated": False,
                              "judge_verdict": "failed", "judge_reason": "held", "judge_progress": "<p1>"}]}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(api_client, "get_config", lambda: CONFIG)
    monkeypatch.setattr(api_client, "list_targets", lambda: [SUMMARY])
    monkeypatch.setattr(api_client, "get_target", lambda target_id: DETAIL)
    monkeypatch.setattr(api_client, "attack_families", lambda: {"library_version": "1.0.0", "families": []})
    monkeypatch.setattr(api_client, "list_runs", lambda target_id: [ADAPTIVE, SINGLE])  # newest first
    monkeypatch.setattr(api_client, "get_run", lambda run_id: ADAPTIVE_DETAIL)
    monkeypatch.setattr(api_client, "get_profile", lambda target_id: {"target_id": 1, "total_runs": 0, "by_family": [], "by_verdict": [], "recent": []})
    return SimpleNamespace()


def loaded() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10).run()
    return at.selectbox(key="target_select").select(1).run()


def test_the_runs_table_has_a_mode_column(api):
    frame = loaded().dataframe[0].value
    assert "Mode" in frame.columns
    assert set(frame["Mode"].tolist()) == {"adaptive", "single-turn"}


def test_opening_an_adaptive_run_shows_the_conversation(api):
    at = loaded()
    at.selectbox(key="open_run").select(6).run()
    code = [b.value for b in at.code]
    assert "<m1>" in code and "<r1>" in code
    assert any("deepseek/deepseek-v3.2" in c.value for c in at.caption)
