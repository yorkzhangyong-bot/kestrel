"""The idle-auto-stop visibility through AppTest (014/FR-061, FR-062, research D30, D31): the target selector's own
cue reads `needs_attention` directly from `GET /api/targets` (never derived locally), and a target's own run list
surfaces the one run that needs attention ahead of the rest, showing its own `idle_stop_at`. Asserted structurally
- never a hard-coded exact cue or heading string, and never two in_progress runs on one target."""
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
          "judge": {"model": "google/gemini-3.8-flash", "configured": True}}

ATTENTION = {"id": 1, "name": "Stuck agent", "url": "http://127.0.0.1:8001/chat", "method": "POST",
             "permission_confirmed_at": "2026-10-23T14:05:00Z", "terms_version": "2", "needs_attention": True}
QUIET = {"id": 2, "name": "Idle agent", "url": "http://127.0.0.1:8002/chat", "method": "POST",
         "permission_confirmed_at": "2026-10-23T14:05:00Z", "terms_version": "2", "needs_attention": False}
DETAIL = {**ATTENTION, "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply", "headers": [],
          "canaries": []}

ATTENTION_RUN = {"id": 7, "target_id": 1, "prompt_id": "spl-002", "prompt_title": "Ask for the prompt",
                 "family": "system_prompt_leak", "owasp_category": "LLM07: System Prompt Leakage",
                 "verdict": None, "hard_evidence": False, "judge_used": False, "judge_model": None,
                 "failure_step": None, "started_at": "2026-10-23T14:00:00Z", "finished_at": None,
                 "memory_written": None, "source_run_id": None, "replay_outcome": None, "finding": False,
                 "replayable": False, "resumable": True, "paused": False, "run_state": "resumable",
                 "pending_turn": None, "idle_stop_at": "2026-10-24T14:00:00Z"}
NORMAL_RUN = {"id": 8, "target_id": 1, "prompt_id": "spl-003", "prompt_title": "Ask again",
              "family": "system_prompt_leak", "owasp_category": "LLM07: System Prompt Leakage",
              "verdict": "failed", "hard_evidence": False, "judge_used": True, "judge_model": "google/gemini-3.8-flash",
              "failure_step": None, "started_at": "2026-10-22T14:00:00Z", "finished_at": "2026-10-22T14:00:03Z",
              "memory_written": True, "source_run_id": None, "replay_outcome": None, "finding": False,
              "replayable": False, "resumable": False, "paused": False, "run_state": "finished",
              "pending_turn": None, "idle_stop_at": None}


@pytest.fixture
def api(monkeypatch):
    stub = SimpleNamespace(runs=[NORMAL_RUN, ATTENTION_RUN])   # deliberately the wrong order: the UI must reorder
    monkeypatch.setattr(api_client, "get_config", lambda: CONFIG)
    monkeypatch.setattr(api_client, "list_targets", lambda: [ATTENTION, QUIET])
    monkeypatch.setattr(api_client, "get_target", lambda target_id: DETAIL)
    monkeypatch.setattr(api_client, "attack_families", lambda: {"library_version": "1.0.0", "families": []})
    monkeypatch.setattr(api_client, "attack_prompts", lambda family: {"prompts": []})
    monkeypatch.setattr(api_client, "get_profile", lambda target_id: {"target_id": 1, "total_runs": 0,
                                                                       "by_family": [], "by_verdict": [],
                                                                       "recent": []})
    monkeypatch.setattr(api_client, "list_runs", lambda target_id: stub.runs)
    monkeypatch.setattr(api_client, "get_run", lambda run_id: next(r for r in stub.runs if r["id"] == run_id))
    return stub


def loaded() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10).run()
    return at.selectbox(key="target_select").select(1).run()


def test_the_target_selector_cues_only_the_needs_attention_target(api):
    at = AppTest.from_file(APP, default_timeout=10).run()

    # The option labels are exactly "name · url" - the cue must never ride the label, whose formatted string
    # Streamlit round-trips: a label that changed between passes would deserialize into a stale string and reset
    # the picker to "New target", blanking the form.
    options = at.selectbox(key="target_select").options
    assert f"{ATTENTION['name']} · {ATTENTION['url']}" in options
    assert all("needs attention" not in opt for opt in options)

    # The cue is a caption beneath the selector: it names the attention target, never the quiet one.
    captions = [c.value for c in at.caption]
    assert any(ATTENTION["name"] in c for c in captions)
    assert not any(QUIET["name"] in c for c in captions)


def test_the_run_that_needs_attention_surfaces_first_with_its_idle_stop_at(api):
    at = loaded()
    frame = at.dataframe[0].value

    # The attention run is reordered ahead of the older, finished one, and its own idle_stop_at is shown.
    assert frame["Prompt"].tolist()[0] == ATTENTION_RUN["prompt_title"]
    assert "auto-stops" in frame["Verdict"].tolist()[0]
    assert "auto-stops" not in frame["Verdict"].tolist()[1]
