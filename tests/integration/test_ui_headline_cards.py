"""The Runs/Confirmed/Suspected headline cards, driven by the server-computed `finding` flag together with
`hard_evidence` - never a mode check of the UI's own (feature 012, FR-027, FR-042)."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import api_client

FEATURE = "012"

APP = str(Path(__file__).resolve().parents[2] / "ui" / "app.py")
CONFIG = {"mode": "local",
          "defaults": {"method": "POST", "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"},
          "terms": {"version": "2", "text": "Terms text."},
          "judge": {"model": "google/gemini-3.8-flash", "configured": True}}
DETAIL = {"id": 1, "name": "My agent", "url": "http://127.0.0.1:8001/chat", "method": "POST",
          "permission_confirmed_at": "2026-10-23T14:05:00Z", "terms_version": "2",
          "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply", "headers": [], "canaries": []}
SUMMARY = {key: DETAIL[key] for key in ("id", "name", "url", "method", "permission_confirmed_at", "terms_version")}


def run(**over):
    base = {"id": 1, "target_id": 1, "prompt_id": "spl-001", "prompt_title": "t", "family": "system_prompt_leak",
            "owasp_category": "LLM07: System Prompt Leakage", "verdict": "succeeded", "hard_evidence": True,
            "judge_used": False, "judge_model": None, "failure_step": None, "started_at": "2026-10-23T14:00:00Z",
            "finished_at": "2026-10-23T14:00:03Z", "mode": "single_turn", "source_run_id": None,
            "replay_outcome": None, "finding": True, "replayable": True, "replay_blocked_reason": None,
            "replay_advisory": None}
    return {**base, **over}


@pytest.fixture
def api(monkeypatch):
    stub = SimpleNamespace(runs=[])
    monkeypatch.setattr(api_client, "get_config", lambda: CONFIG)
    monkeypatch.setattr(api_client, "list_targets", lambda: [SUMMARY])
    monkeypatch.setattr(api_client, "get_target", lambda target_id: DETAIL)
    monkeypatch.setattr(api_client, "attack_families", lambda: {"library_version": "1.0.0", "families": []})
    monkeypatch.setattr(api_client, "get_profile", lambda target_id: {"target_id": 1, "total_runs": 0,
                                                                      "by_family": [], "by_verdict": [],
                                                                      "recent": []})
    monkeypatch.setattr(api_client, "list_runs", lambda target_id: stub.runs)
    return stub


def loaded() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10).run()
    return at.selectbox(key="target_select").select(1).run()


def metric_value(at: AppTest, label: str) -> str:
    return next(m.value for m in at.metric if m.label == label)


def test_confirmed_suspected_and_runs_split_correctly_with_a_replay_in_the_mix(api):
    """One boolean cannot produce two cards: the fixture carries a confirmed finding, a suspected finding, and a
    succeeded replay (excluded from both, still counted in Runs) all at once, proving the split itself."""
    api.runs = [
        run(id=1, hard_evidence=True, finding=True),                                    # confirmed
        run(id=2, hard_evidence=False, judge_used=True, judge_model="j/m", finding=True),  # suspected
        run(id=3, mode="replay", source_run_id=1, replay_outcome="still_vulnerable",
           verdict="succeeded", hard_evidence=False, finding=False),                    # a replay: neither card
    ]
    at = loaded()

    assert metric_value(at, "Runs") == "3"
    assert metric_value(at, "Confirmed") == "1"
    assert metric_value(at, "Suspected") == "1"


def test_a_failed_run_counts_toward_neither_card(api):
    api.runs = [run(id=1, verdict="failed", hard_evidence=False, finding=False)]
    at = loaded()

    assert metric_value(at, "Runs") == "1"
    assert metric_value(at, "Confirmed") == "0"
    assert metric_value(at, "Suspected") == "0"
