"""The sidebar shows the active prompt versions (id + version), never the prompt text (009/FR-007, 009/SC-004)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import api_client

FEATURE = "009"

APP = str(Path(__file__).resolve().parents[2] / "ui" / "app.py")
PROMPTS = [{"id": "attacker:direct_injection", "version": "1"},
           {"id": "judge", "version": "1"},
           {"id": "recommender", "version": "1"}]
CONFIG = {"mode": "local",
          "defaults": {"method": "POST", "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"},
          "terms": {"version": "7", "text": "Terms text."},
          "judge": {"model": "google/gemini-3.8-flash", "configured": True},
          "attacker": {"model": "deepseek/deepseek-v4.1-flash", "configured": True},
          "adaptive": {"max_turns": 6, "token_budget": 40000, "time_limit_s": 300},
          "experience": {"pattern_k": 5, "memory_cap": 50, "use_prior_experience_default": True},
          "prompts": PROMPTS}
SUMMARY = {"id": 1, "name": "My agent", "url": "http://127.0.0.1:8001/chat", "method": "POST",
           "permission_confirmed_at": "2026-10-30T14:05:00Z", "terms_version": "7"}
DETAIL = {**SUMMARY, "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply",
          "headers": [], "canaries": []}
FAMILIES = {"library_version": "1.0.0", "families": []}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(api_client, "get_config", lambda: CONFIG)
    monkeypatch.setattr(api_client, "list_targets", lambda: [SUMMARY])
    monkeypatch.setattr(api_client, "get_target", lambda target_id: DETAIL)
    monkeypatch.setattr(api_client, "attack_families", lambda: FAMILIES)
    monkeypatch.setattr(api_client, "attack_prompts", lambda family: {"prompts": []})
    monkeypatch.setattr(api_client, "list_runs", lambda target_id: [])
    monkeypatch.setattr(api_client, "get_profile", lambda target_id: {
        "target_id": 1, "total_runs": 0, "by_family": [], "by_verdict": [], "recent": []})


def test_the_sidebar_shows_active_prompt_versions(api):  # 009/FR-007, 009/SC-004
    at = AppTest.from_file(APP, default_timeout=10).run()
    captions = [c.value for c in at.caption]
    assert "attacker:direct_injection · 1" in captions
    assert "judge · 1" in captions
    assert "recommender · 1" in captions


def test_no_prompt_text_is_shown(api):  # 009/SC-004
    at = AppTest.from_file(APP, default_timeout=10).run()
    rows = [v for v in (c.value for c in at.caption) if " · " in v and v.split(" · ")[-1] == "1"]
    assert rows and all(len(r) < 60 for r in rows)   # only "<id> · <version>", never the template text
