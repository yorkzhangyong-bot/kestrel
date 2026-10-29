"""The adaptive mode toggle and conversation display through AppTest (contracts/ui-screen.md, FR-001/023/024)."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import api_client

FEATURE = "003"

APP = str(Path(__file__).resolve().parents[2] / "ui" / "app.py")
CONFIG = {"mode": "local",
          "defaults": {"method": "POST", "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"},
          "terms": {"version": "3", "text": "Terms text."},
          "judge": {"model": "google/gemini-3.8-flash", "configured": True},
          "attacker": {"model": "deepseek/deepseek-v3.2", "configured": True},
          "adaptive": {"max_turns": 6, "token_budget": 40000, "time_limit_s": 300}}
DETAIL = {"id": 1, "name": "My agent", "url": "http://127.0.0.1:8001/chat", "method": "POST",
          "permission_confirmed_at": "2026-10-24T14:05:00Z", "terms_version": "3",
          "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply",
          "headers": [{"name": "X-API-Key", "has_value": True, "readable": True}], "canaries": []}
SUMMARY = {k: DETAIL[k] for k in ("id", "name", "url", "method", "permission_confirmed_at", "terms_version")}
FAMILIES = [{"key": "system_prompt_leak", "label": "System prompt leak",
             "owasp_category": "LLM07: System Prompt Leakage", "prompt_count": 4}]
HOSTILE = '<script>alert(1)</script> [l](http://evil.test) ![i](http://evil.test/i.png)'

ADAPTIVE_RUN = {"id": 9, "target_id": 1, "mode": "adaptive", "prompt_id": "spl-002", "prompt_title": "t",
                "family": "system_prompt_leak", "owasp_category": "LLM07: System Prompt Leakage", "status": "finished",
                "verdict": "failed", "hard_evidence": False, "judge_used": True, "judge_model": "google/gemini-3.8-flash",
                "failure_step": None, "started_at": "2026-10-24T14:00:00Z", "finished_at": "2026-10-24T14:00:30Z",
                "prompt_text": "<seed>", "reply_text": None, "reply_truncated": False, "reason": "The agent held.",
                "attacker_source": "library:1.0.0", "attacker_model": "deepseek/deepseek-v3.2", "turn_budget": 6,
                "turns_used": 3, "token_budget": 40000, "tokens_used": 2200, "time_limit_s": 300,
                "stopping_condition": "turn_cap", "succeeded_turn": None,
                "turns": [{"position": 1, "attacker_message": "<m1>", "reply_text": f"<r1> {HOSTILE}",
                           "reply_truncated": False, "judge_verdict": "failed", "judge_reason": "held",
                           "judge_progress": "<p1>"},
                          {"position": 2, "attacker_message": "<m2>", "reply_text": "<r2>", "reply_truncated": False,
                           "judge_verdict": "failed", "judge_reason": "held", "judge_progress": "<p2>"}]}


@pytest.fixture
def api(monkeypatch, request):
    attacker_configured = getattr(request, "param", True)
    cfg = {**CONFIG, "attacker": {"model": "deepseek/deepseek-v3.2", "configured": attacker_configured}}
    stub = SimpleNamespace(runs=[])

    def run_attack(payload):
        stub.runs.append(payload)
        return ADAPTIVE_RUN

    monkeypatch.setattr(api_client, "get_config", lambda: cfg)
    monkeypatch.setattr(api_client, "list_targets", lambda: [SUMMARY])
    monkeypatch.setattr(api_client, "get_target", lambda target_id: DETAIL)
    monkeypatch.setattr(api_client, "attack_families", lambda: {"library_version": "1.0.0", "families": FAMILIES})
    monkeypatch.setattr(api_client, "attack_prompts", lambda family: {"prompts": []})
    monkeypatch.setattr(api_client, "run_attack", run_attack)
    monkeypatch.setattr(api_client, "list_runs", lambda target_id: [ADAPTIVE_RUN])
    monkeypatch.setattr(api_client, "get_run", lambda run_id: ADAPTIVE_RUN)
    monkeypatch.setattr(api_client, "get_profile", lambda target_id: {"target_id": 1, "total_runs": 0, "by_family": [], "by_verdict": [], "recent": []})
    return stub


def loaded() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10).run()
    return at.selectbox(key="target_select").select(1).run()


def test_the_mode_toggle_is_present_and_defaults_to_single_turn(api):
    at = loaded()
    mode = at.radio(key="attack_mode")
    assert mode.value == "Single-turn" and "Adaptive" in mode.options


def test_running_in_adaptive_mode_sends_mode_adaptive(api):
    at = loaded()
    at.radio(key="attack_mode").set_value("Adaptive").run()
    at.button(key="run_button").click().run()
    assert api.runs[-1]["mode"] == "adaptive"


def test_the_conversation_is_shown_turn_by_turn(api):
    at = loaded()
    at.radio(key="attack_mode").set_value("Adaptive").run()
    at.button(key="run_button").click().run()
    code = [b.value for b in at.code]
    assert "<m1>" in code and "<m2>" in code                     # attacker messages
    assert any("<r1>" in c for c in code) and "<r2>" in code     # agent replies


def test_a_hostile_reply_in_the_conversation_is_shown_as_text(api):
    at = loaded()
    at.radio(key="attack_mode").set_value("Adaptive").run()
    at.button(key="run_button").click().run()
    assert any(HOSTILE in c for c in [b.value for b in at.code])
    assert not any(HOSTILE in m.value for m in at.markdown)


def test_the_footer_names_the_attacker_and_budget(api):
    at = loaded()
    at.radio(key="attack_mode").set_value("Adaptive").run()
    at.button(key="run_button").click().run()
    captions = " ".join(c.value for c in at.caption)
    assert "deepseek/deepseek-v3.2" in captions and "3/6 turns" in captions


@pytest.mark.parametrize("api", [False], indirect=True)
def test_run_is_disabled_in_adaptive_mode_without_an_attacker(api):
    at = loaded()
    at.radio(key="attack_mode").set_value("Adaptive").run()
    assert at.button(key="run_button").disabled is True
