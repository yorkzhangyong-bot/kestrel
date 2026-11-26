"""The Resume/Stop controls, rendered from `run_state` alone (014/FR-014, FR-054)."""
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
            "replay_advisory": None, "comparison": None, "turns": [], "resumable": False, "paused": False,
            "run_state": "running", "pending_turn": None}
    return {**base, **over}


@pytest.fixture
def api(monkeypatch):
    stub = SimpleNamespace(runs=[], resume_error=None, stop_error=None)

    def resume_run(run_id):
        if stub.resume_error is not None:
            raise stub.resume_error
        return {}

    def stop_run(run_id):
        if stub.stop_error is not None:
            raise stub.stop_error
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
    monkeypatch.setattr(api_client, "resume_run", resume_run)
    monkeypatch.setattr(api_client, "stop_run", stop_run)
    return stub


def loaded() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10).run()
    return at.selectbox(key="target_select").select(1).run()


def opened(api, the_run: dict) -> AppTest:
    api.runs = [the_run]
    at = loaded()
    return at.selectbox(key="open_run").select(the_run["id"]).run()


def buttons_named(at: AppTest, prefix: str, run_id: int):
    return [b.label for b in at.button if b.key and b.key.startswith(f"{prefix}_button_opened_{run_id}")]


def test_run_state_running_shows_no_control(api):
    at = opened(api, run(run_state="running"))
    assert "resume" not in [b.key for b in at.button if b.key] and \
        not any(k.key and k.key.startswith(("resume_button", "stop_button")) for k in at.button)


def test_run_state_stoppable_shows_stop_alone_never_resume(api):
    at = opened(api, run(run_state="stoppable", status="finished"))
    keys = [b.key for b in at.button if b.key]
    assert any(k.startswith("stop_button_opened_7") for k in keys)
    assert not any(k.startswith("resume_button_opened_7") for k in keys)


def test_run_state_resumable_shows_both_resume_and_stop(api):
    at = opened(api, run(run_state="resumable", resumable=True))
    keys = [b.key for b in at.button if b.key]
    assert any(k.startswith("resume_button_opened_7") for k in keys)
    assert any(k.startswith("stop_button_opened_7") for k in keys)


def test_resuming_calls_the_api_and_shows_an_error_on_failure(api):
    api.resume_error = api_client.ApiError(409, {"error": {"code": "pinned_model_unavailable", "field": None,
                                                           "message": "This run's own pinned model is gone."}})
    at = opened(api, run(run_state="resumable", resumable=True))
    resume_key = next(b.key for b in at.button if b.key and b.key.startswith("resume_button_opened_7"))
    at = at.button(key=resume_key).click().run()
    assert any("pinned model is gone" in e.value for e in at.error)
