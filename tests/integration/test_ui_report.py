"""The Report section after Profile: generate, preview, downloads, and the empty state (feature 005, contracts/ui-screen.md)."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

import api_client

APP = str(Path(__file__).resolve().parents[2] / "ui" / "app.py")
CONFIG = {"mode": "local",
          "defaults": {"method": "POST", "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"},
          "terms": {"version": "4", "text": "Terms."},
          "judge": {"model": "google/gemini-3.8-flash", "configured": True},
          "attacker": {"model": "deepseek/deepseek-v4.1-flash", "configured": True},
          "adaptive": {"max_turns": 6, "token_budget": 40000, "time_limit_s": 300},
          "experience": {"pattern_k": 5, "memory_cap": 10, "use_prior_experience_default": True}}
DETAIL = {"id": 1, "name": "My agent", "url": "http://127.0.0.1:8001/chat", "method": "POST",
          "permission_confirmed_at": "2026-10-28T14:05:00Z", "terms_version": "4", "description": "a customs assistant",
          "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply", "headers": [], "canaries": []}
SUMMARY = {k: DETAIL[k] for k in ("id", "name", "url", "method", "permission_confirmed_at", "terms_version",
                                  "description")}
RUN = {"id": 5, "target_id": 1, "mode": "single_turn", "prompt_id": "spl-001", "prompt_title": "one",
       "family": "system_prompt_leak", "owasp_category": "LLM07: System Prompt Leakage", "verdict": "failed",
       "hard_evidence": False, "judge_used": True, "judge_model": "google/gemini-3.8-flash", "failure_step": None,
       "started_at": "2026-10-28T13:00:00Z", "finished_at": "2026-10-28T13:00:05Z", "memory_written": True,
       "use_prior_experience": True}
REPORT_MD = "# Security report — My agent\n\n## Findings\n\nNo successful attacks recorded.\n\n## Limitations\n\nCovers only what was run.\n"


def base(monkeypatch, runs):
    monkeypatch.setattr(api_client, "get_config", lambda: CONFIG)
    monkeypatch.setattr(api_client, "list_targets", lambda: [SUMMARY])
    monkeypatch.setattr(api_client, "get_target", lambda target_id: DETAIL)
    monkeypatch.setattr(api_client, "attack_families", lambda: {"library_version": "1.0.0", "families": []})
    monkeypatch.setattr(api_client, "attack_prompts", lambda family: {"prompts": []})
    monkeypatch.setattr(api_client, "list_runs", lambda target_id: runs)
    monkeypatch.setattr(api_client, "get_run", lambda run_id: RUN)
    monkeypatch.setattr(api_client, "get_profile", lambda target_id:
                        {"target_id": 1, "total_runs": len(runs), "by_family": [], "by_verdict": [], "recent": []})
    monkeypatch.setattr(api_client, "get_report", lambda target_id, fmt: REPORT_MD)


def loaded() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10).run()
    return at.selectbox(key="target_select").select(1).run()


def test_generate_shows_a_preview(monkeypatch):
    base(monkeypatch, [RUN])
    at = loaded()
    assert [b for b in at.button if b.key == "generate_report"], "the Generate report button is shown"
    at.button(key="generate_report").click().run()
    assert any("Security report — My agent" in m.value for m in at.markdown)   # preview rendered


def test_empty_state_when_no_runs(monkeypatch):
    base(monkeypatch, [])
    at = loaded()
    assert any("No runs to report yet" in c.value for c in at.caption)
    assert not [b for b in at.button if b.key == "generate_report"]
