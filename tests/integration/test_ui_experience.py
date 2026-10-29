"""The screen surfaces for feature 004: the experience toggle, the purpose field, the write-back warning, the
profile (contracts/ui-screen.md, FR-010, FR-014, FR-020, FR-022)."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import api_client

FEATURE = "004"

APP = str(Path(__file__).resolve().parents[2] / "ui" / "app.py")
CONFIG = {"mode": "local",
          "defaults": {"method": "POST", "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"},
          "terms": {"version": "4", "text": "Terms."},
          "judge": {"model": "google/gemini-3.8-flash", "configured": True},
          "attacker": {"model": "deepseek/deepseek-v3.2", "configured": True},
          "adaptive": {"max_turns": 6, "token_budget": 40000, "time_limit_s": 300},
          "experience": {"pattern_k": 5, "memory_cap": 10, "use_prior_experience_default": True}}
DETAIL = {"id": 1, "name": "My agent", "url": "http://127.0.0.1:8001/chat", "method": "POST",
          "permission_confirmed_at": "2026-10-24T14:05:00Z", "terms_version": "4",
          "description": "a customs classification assistant",
          "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply", "headers": [], "canaries": []}
SUMMARY = {k: DETAIL[k] for k in ("id", "name", "url", "method", "permission_confirmed_at", "terms_version",
                                  "description")}
RUN = {"id": 7, "target_id": 1, "mode": "single_turn", "prompt_id": "spl-001", "prompt_title": "one",
       "family": "system_prompt_leak", "owasp_category": "LLM07: System Prompt Leakage", "verdict": "failed",
       "hard_evidence": False, "judge_used": True, "judge_model": "google/gemini-3.8-flash", "failure_step": None,
       "started_at": "2026-10-24T14:00:00Z", "finished_at": "2026-10-24T14:00:05Z", "memory_written": False,
       "use_prior_experience": True}
RUN_DETAIL = {**RUN, "status": "finished", "prompt_text": "<seed>", "reply_text": "<reply>", "reply_truncated": False,
              "reason": "held", "attacker_source": "library:1.0.0", "turns": []}
PROFILE = {"target_id": 1, "total_runs": 2,
           "by_family": [{"family": "system_prompt_leak", "count": 2}],
           "by_verdict": [{"verdict": "failed", "count": 2}],
           "recent": [{"summary": "held both times", "family": "system_prompt_leak", "verdict": "failed",
                       "created_at": "2026-10-24T14:00:05Z"}]}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(api_client, "get_config", lambda: CONFIG)
    monkeypatch.setattr(api_client, "list_targets", lambda: [SUMMARY])
    monkeypatch.setattr(api_client, "get_target", lambda target_id: DETAIL)
    monkeypatch.setattr(api_client, "attack_families", lambda: {"library_version": "1.0.0", "families": [
        {"key": "system_prompt_leak", "label": "System prompt leak", "owasp_category": "LLM07: System Prompt Leakage",
         "prompt_count": 4}]})
    monkeypatch.setattr(api_client, "attack_prompts", lambda family: {"prompts": []})
    monkeypatch.setattr(api_client, "list_runs", lambda target_id: [RUN])
    monkeypatch.setattr(api_client, "get_run", lambda run_id: RUN_DETAIL)
    monkeypatch.setattr(api_client, "get_profile", lambda target_id: PROFILE)
    return SimpleNamespace()


def loaded() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10).run()
    return at.selectbox(key="target_select").select(1).run()


def test_the_attack_panel_has_the_experience_toggle_default_on(api):
    at = loaded()
    toggles = [t for t in at.toggle if t.key == "use_prior_experience"]
    assert toggles and toggles[0].value is True   # default warm (FR-014)


def test_the_form_has_the_purpose_field_filled_from_the_target(api):
    at = loaded()
    field = at.text_input(key="description")
    assert field.value == "a customs classification assistant"   # FR-020


def test_a_run_not_written_back_shows_a_warning(api):
    at = loaded()
    at.selectbox(key="open_run").select(7).run()
    assert any("experience store" in w.value.lower() for w in at.warning)   # FR-010


def test_the_profile_shows_counts_and_recent_summaries(api):
    at = loaded()
    texts = [t.value for t in at.text] + [c.value for c in at.code] + [c.value for c in at.caption]
    blob = " ".join(texts)
    assert "system_prompt_leak" in blob and "held both times" in blob   # FR-022
