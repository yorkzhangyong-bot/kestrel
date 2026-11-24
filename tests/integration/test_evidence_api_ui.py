"""Every evidence item is visible on the API, the run page and the run list, with the exact texts of FR-039 and
FR-040 (013/FR-005, FR-038 to FR-043, SC-004, SC-008).

The API composes every label, line and notice; the screen only displays them. A run recorded before this feature
— hard evidence set, no stored items — reads as exactly one canary item on every surface, and a run without
items keeps today's run-list text, so no existing row changes."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from streamlit.testing.v1 import AppTest

import api_client
from kestrel.evidence import unsafe_output
from tests.support import StubAttacker, StubJudge, fixture_library, planted_values, saved_target

FEATURE = "013"

APP = str(Path(__file__).resolve().parents[2] / "ui" / "app.py")


def api_client_for(make_client, settings, reply: str, *, canaries=None):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"reply": reply}))
    api = make_client(settings, transport=transport, library=fixture_library(), judge=StubJudge(verdict="failed"),
                      attacker=StubAttacker())
    target = saved_target(api.app.state.store, canaries=canaries)
    return api, target


def confirmed_run(api, target, *, family="system_prompt_leak", seed_id="spl-001"):
    response = api.post("/api/runs", json={"target_id": target.id, "family": family, "prompt_id": seed_id})
    assert response.status_code == 201, response.text
    return response.json()


# ---- the API shapes (FR-038, SC-004) ----


def test_the_run_summary_and_detail_carry_the_evidence_fields(make_client, settings):  # FR-038, SC-004
    sample = "KESTREL-CANARY-7Q4M2X"
    api, target = api_client_for(make_client, settings, f"it leaked {sample}", canaries=[sample])

    run = confirmed_run(api, target)

    assert run["evidence_kinds"] == ["canary_in_reply"] and run["evidence_labels"] == ["canary"]
    assert run["evidence_count"] == 1 and run["side_channel_status"] == "not_configured"
    item = run["evidence"][0]
    assert item["kind"] == "canary_in_reply" and item["label"] == "canary" and item["turn"] == 1
    assert item["location"] == "reply" and item["location_label"] == "in the reply"
    assert item["owasp_category"] == "LLM07: System Prompt Leakage" and item["detail"] == sample
    assert item["line"] == "canary · turn 1 · in the reply · LLM07: System Prompt Leakage"
    assert item["pattern_name"] is None and item["created_at"]
    assert run["planted_tokens"] == [] and run["side_channel_notice"] is None
    assert run["override_disarmed_notice"] is None and run["callback_note"] is None

    listed = api.get(f"/api/targets/{target.id}/runs").json()[0]
    assert listed["evidence_kinds"] == ["canary_in_reply"] and listed["evidence_labels"] == ["canary"]
    assert listed["evidence_count"] == 1


def test_a_planted_run_reports_its_token_without_the_value(make_client, settings):  # FR-038
    api, target = api_client_for(make_client, settings, "an ordinary reply")

    run = confirmed_run(api, target, family="direct_injection", seed_id="dir-001")

    detail = api.get(f"/api/runs/{run['id']}").json()
    assert detail["planted_tokens"] == [{"kind": "override", "armed": True, "disarmed_turn": None,
                                         "prompt": "override_task@1"}]
    values = planted_values(api.app.state.store, run["id"])
    body = api.get(f"/api/runs/{run['id']}").text
    assert values["joined"] not in body.replace(detail["prompt_text"], "")   # only the stored message carries it


def test_an_unsafe_output_item_carries_its_pattern_name_and_set_version(make_client, settings):  # FR-017, SC-004
    import json
    cases = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "unsafe_output_cases.json")
                       .read_text(encoding="utf-8"))["cases"]
    sample = next(c["text"] for c in cases if c["pattern"] == "drop_or_truncate_table" and c["kind"] == "positive")
    api, target = api_client_for(make_client, settings, sample)

    run = confirmed_run(api, target)

    item = run["evidence"][0]
    assert item["kind"] == "unsafe_executable_output" and item["label"] == "unsafe executable output"
    assert item["pattern_name"] == "drop_or_truncate_table"
    assert item["pattern_set_version"] == unsafe_output.PATTERN_SET_VERSION
    assert item["line"] == "unsafe executable output · turn 1 · in the reply · LLM05: Improper Output Handling"


def test_a_pre_013_hard_evidence_run_reads_as_one_canary_item_everywhere(make_client, settings):  # FR-005, FR-040
    api, target = api_client_for(make_client, settings, "an ordinary reply")
    store = api.app.state.store
    # A row as feature 012 would have left it: hard evidence, no stored items.
    run_id = store.claim_run(target.id, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0")
    store.finish_run(run_id, verdict="succeeded", hard_evidence=True, reply_text="leaked")
    assert store.list_evidence(run_id) == []

    detail = api.get(f"/api/runs/{run_id}").json()
    listed = next(r for r in api.get(f"/api/targets/{target.id}/runs").json() if r["id"] == run_id)

    for shape in (detail, listed):
        assert shape["evidence_kinds"] == ["canary_in_reply"] and shape["evidence_labels"] == ["canary"]
        assert shape["evidence_count"] == 1
    assert [item["kind"] for item in detail["evidence"]] == ["canary_in_reply"]
    assert detail["evidence"][0]["turn"] == 1
    assert detail["evidence"][0]["owasp_category"] == "LLM07: System Prompt Leakage"


def test_the_config_reports_the_evidence_settings(client):  # FR-042
    evidence = client.get("/api/config").json()["evidence"]
    assert evidence["callback_listener"] is False          # part 1 mounts no listener route (FR-073)
    assert evidence["callback_wait_s"] == 2.0 and evidence["side_channel_timeout_s"] == 10
    assert evidence["detectors"] == ["instruction_override", "unsafe_executable_output"]
    assert evidence["unsafe_output_categories"] == list(unsafe_output.CATEGORIES)
    assert evidence["unsafe_output_pattern_set_version"] == unsafe_output.PATTERN_SET_VERSION


# ---- the screen (FR-039, FR-040, FR-043, SC-004) ----


CONFIG = {"mode": "local",
          "defaults": {"method": "POST", "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"},
          "terms": {"version": "2", "text": "Terms text."},
          "judge": {"model": "google/gemini-3.8-flash", "configured": True}}
TARGET = {"id": 1, "name": "My agent", "url": "http://127.0.0.1:8001/chat", "method": "POST",
          "permission_confirmed_at": "2026-11-20T14:05:00Z", "terms_version": "2",
          "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply", "headers": [], "canaries": []}
SUMMARY = {key: TARGET[key] for key in ("id", "name", "url", "method", "permission_confirmed_at", "terms_version")}
BASE_RUN = {"id": 7, "target_id": 1, "mode": "single_turn", "prompt_id": "dir-001", "prompt_title": "A seed",
            "family": "direct_injection", "owasp_category": "LLM01: Prompt Injection", "verdict": "succeeded",
            "hard_evidence": True, "judge_used": False, "judge_model": None, "failure_step": None,
            "started_at": "2026-11-20T14:00:00Z", "finished_at": "2026-11-20T14:00:03Z", "status": "finished",
            "prompt_text": "<the sent message>", "reply_text": "<the reply>", "reply_truncated": False,
            "reason": "Hard evidence confirmed the attack: instruction override.", "attacker_source": "library:1.0.0",
            "finding": True, "replayable": False, "replay_blocked_reason": None, "replay_advisory": None,
            "evidence_kinds": ["instruction_override"], "evidence_labels": ["instruction override"],
            "evidence_count": 1, "side_channel_status": "not_configured",
            "evidence": [{"kind": "instruction_override", "label": "instruction override", "turn": 1,
                          "location": "reply", "location_label": "in the reply",
                          "owasp_category": "LLM01: Prompt Injection",
                          "detail": "the planted marker appeared in the reply",
                          "line": "instruction override · turn 1 · in the reply · LLM01: Prompt Injection",
                          "pattern_name": None, "pattern_set_version": None,
                          "created_at": "2026-11-20T14:00:03Z"}],
            "planted_tokens": [{"kind": "override", "armed": True, "disarmed_turn": None,
                                "prompt": "override_task@1"}],
            "side_channel_notice": None, "override_disarmed_notice": None, "callback_note": None}


@pytest.fixture
def screen(monkeypatch):
    state = SimpleNamespace(run=dict(BASE_RUN), runs=[dict(BASE_RUN)])
    monkeypatch.setattr(api_client, "get_config", lambda: CONFIG)
    monkeypatch.setattr(api_client, "list_targets", lambda: [SUMMARY])
    monkeypatch.setattr(api_client, "get_target", lambda target_id: TARGET)
    monkeypatch.setattr(api_client, "attack_families", lambda: {"library_version": "1.0.0", "families": []})
    monkeypatch.setattr(api_client, "list_runs", lambda target_id: state.runs)
    monkeypatch.setattr(api_client, "get_run", lambda run_id: state.run)
    monkeypatch.setattr(api_client, "get_profile", lambda target_id: {"target_id": 1, "total_runs": 0,
                                                                      "by_family": [], "by_verdict": [],
                                                                      "recent": []})
    return state


def opened(run_id: int = 7) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10).run()
    at = at.selectbox(key="target_select").select(1).run()
    return at.selectbox(key="open_run").select(run_id).run()


def test_the_headline_names_every_confirming_kind(screen):  # FR-039, SC-004
    screen.run = {**BASE_RUN, "evidence_kinds": ["canary_in_reply", "unsafe_executable_output"],
                  "evidence_labels": ["canary", "unsafe executable output"], "evidence_count": 2}
    at = opened()
    assert any(e.value == "Attack succeeded · confirmed by canary + unsafe executable output" for e in at.error)


def test_an_adaptive_headline_appends_the_turn(screen):  # FR-039
    screen.run = {**BASE_RUN, "mode": "adaptive", "succeeded_turn": 3, "turns": []}
    at = opened()
    assert any(e.value == "Attack succeeded · confirmed by instruction override at turn 3" for e in at.error)


def test_the_evidence_section_lists_one_exact_line_per_item_then_its_detail(screen):  # FR-039, SC-004
    at = opened()
    assert any(h.value == "Evidence" for h in at.subheader)
    assert any(c.value == "instruction override · turn 1 · in the reply · LLM01: Prompt Injection"
               for c in at.caption)
    assert any(t.value == "the planted marker appeared in the reply" for t in at.text)


def test_the_notices_render_only_when_the_api_sets_them(screen):  # FR-039, FR-043
    assert not any("disarmed" in w.value for w in opened().warning)
    screen.run = {**BASE_RUN, "override_disarmed_notice": "The override token was disarmed on turn 2.",
                  "side_channel_notice": "The side channel couldn't be read during this run, so tool-call and "
                                         "state evidence may be missing."}
    at = opened()
    values = [w.value for w in at.warning]
    assert "The override token was disarmed on turn 2." in values
    assert ("The side channel couldn't be read during this run, so tool-call and state evidence may be missing."
            in values)


def test_the_run_list_joins_the_kind_labels(screen):  # FR-040, SC-004
    screen.runs = [{**BASE_RUN, "evidence_labels": ["canary", "instruction override"]}]
    at = AppTest.from_file(APP, default_timeout=10).run().selectbox(key="target_select").select(1).run()
    assert "canary + instruction override" in at.dataframe[0].value["Evidence"].tolist()


@pytest.mark.parametrize("run, expected", [
    ({"hard_evidence": True, "judge_used": False, "evidence_labels": [], "evidence_kinds": []}, "canary"),
    ({"hard_evidence": False, "judge_used": True, "judge_model": "google/gemini-3.8-flash",
      "evidence_labels": [], "evidence_kinds": [], "verdict": "failed"}, "judge · google/gemini-3.8-flash"),
    ({"hard_evidence": False, "judge_used": False, "evidence_labels": [], "evidence_kinds": [],
      "verdict": "unclear"}, "—"),
    ({"hard_evidence": False, "judge_used": True, "failure_step": "unreachable", "evidence_labels": [],
      "evidence_kinds": [], "verdict": None}, "—"),
])
def test_a_run_without_items_keeps_todays_run_list_text(screen, run, expected):  # FR-040, SC-008
    screen.runs = [{**BASE_RUN, **run}]
    at = AppTest.from_file(APP, default_timeout=10).run().selectbox(key="target_select").select(1).run()
    assert at.dataframe[0].value["Evidence"].tolist() == [expected]
