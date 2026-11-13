"""The run page's Log viewer through AppTest, api_client stubbed (010/FR-012, 010/SC-002, 010/SC-003): every opened
run — a send-failed one included — has a collapsed "Log" expander listing its kept lines (time, event, turn, model,
prompt, latency, tokens, cost) with the raw JSON; an empty log says so; a truncated one shows its drop count. The
screen reads the lines only through api_client. Placeholders only."""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import api_client
from tests.support import ATTACK_TEXT, REPLY_TEXT, SECRET, TARGET_NAME, TARGET_URL

FEATURE = "010"

APP = str(Path(__file__).resolve().parents[2] / "ui" / "app.py")
CONFIG = {"mode": "local",
          "defaults": {"method": "POST", "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"},
          "terms": {"version": "7", "text": "Terms text."},
          "judge": {"model": "google/gemini-3.8-flash", "configured": True}}
SUMMARY = {"id": 1, "name": "My agent", "url": "http://127.0.0.1:8001/chat", "method": "POST",
           "permission_confirmed_at": "2026-11-13T09:00:00Z", "terms_version": "7"}
DETAIL = {**SUMMARY, "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply", "headers": [],
          "canaries": []}
RUN_SUMMARY = {"id": 7, "target_id": 1, "prompt_id": "spl-002", "prompt_title": "Ask for the prompt",
               "family": "system_prompt_leak", "owasp_category": "LLM07: System Prompt Leakage", "verdict": "failed",
               "hard_evidence": False, "judge_used": True, "judge_model": "google/gemini-3.8-flash",
               "failure_step": None, "started_at": "2026-11-13T10:15:00Z", "finished_at": "2026-11-13T10:15:03Z"}
RUN_DETAIL = {**RUN_SUMMARY, "status": "finished", "prompt_text": ATTACK_TEXT, "reply_text": REPLY_TEXT,
              "reply_truncated": False, "reason": "The agent refused.", "attacker_source": "library:1.0.0"}
SCOPE = {"run_id": 7, "target_id": 1, "mode": "single_turn", "family": "system_prompt_leak"}
LINES = [
    {"ts": "2026-11-13T10:15:00.004Z", "level": "INFO", "logger": "kestrel", "event": "run.start", **SCOPE,
     "prompt_id": "spl-002", "judge_model": "google/gemini-3.8-flash", "judge_prompt": "judge@1"},
    {"ts": "2026-11-13T10:15:00.051Z", "level": "INFO", "logger": "kestrel.connection", "event": "target.request",
     **SCOPE, "turn": 1, "latency_ms": 41, "ok": True, "status": 200, "step": "success", "reply_chars": 22},
    {"ts": "2026-11-13T10:15:00.963Z", "level": "INFO", "logger": "kestrel", "event": "model.request", **SCOPE,
     "turn": 1, "kind": "judge", "model": "google/gemini-3.8-flash", "prompt": "judge@1", "latency_ms": 912,
     "ok": True, "status": 200, "attempts": 1, "total_tokens": 698, "cost_usd": 0.001047, "verdict": "failed",
     "hard_evidence": False},
    {"ts": "2026-11-13T10:15:00.964Z", "level": "INFO", "logger": "kestrel", "event": "turn", **SCOPE, "turn": 1,
     "source": "library:spl-002", "total_tokens": 698, "cost_usd": 0.001047, "judged": True, "verdict": "failed"},
    {"ts": "2026-11-13T10:15:01.010Z", "level": "INFO", "logger": "kestrel", "event": "memory.writeback", **SCOPE,
     "written": True, "pattern_written": False},
    {"ts": "2026-11-13T10:15:01.011Z", "level": "INFO", "logger": "kestrel", "event": "run.end", **SCOPE,
     "verdict": "failed", "judge_used": True, "duration_ms": 1007, "cost_usd": 0.001047},
]
COLUMNS = ["Time", "Event", "Turn", "Model", "Prompt", "Latency ms", "Tokens", "Cost"]


@pytest.fixture
def api(monkeypatch):
    state = {"run": RUN_DETAIL, "log": {"run_id": 7, "lines": LINES, "kept": len(LINES), "dropped": 0,
                                        "truncated": False}, "asked": []}

    def get_run_log(run_id):
        state["asked"].append(run_id)
        if isinstance(state["log"], Exception):
            raise state["log"]
        return state["log"]

    monkeypatch.setattr(api_client, "get_config", lambda: CONFIG)
    monkeypatch.setattr(api_client, "list_targets", lambda: [SUMMARY])
    monkeypatch.setattr(api_client, "get_target", lambda target_id: DETAIL)
    monkeypatch.setattr(api_client, "attack_families", lambda: {"library_version": "1.0.0", "families": []})
    monkeypatch.setattr(api_client, "list_runs", lambda target_id: [RUN_SUMMARY])
    monkeypatch.setattr(api_client, "get_run", lambda run_id: state["run"])
    monkeypatch.setattr(api_client, "get_run_log", get_run_log)
    monkeypatch.setattr(api_client, "get_profile", lambda target_id: {
        "target_id": 1, "total_runs": 0, "by_family": [], "by_verdict": [], "recent": []})
    return state


def opened(api) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10).run()
    at = at.selectbox(key="target_select").select(1).run()
    return at.selectbox(key="open_run").select(7).run()


def log_expander(at):
    found = [block for block in at.expander if block.label == "Log"]
    assert len(found) == 1, [block.label for block in at.expander]
    return found[0]


def test_an_opened_run_has_a_collapsed_log_with_one_row_per_line(api):  # FR-012, SC-003
    log = log_expander(opened(api))
    assert not log.proto.expanded and api["asked"] == [7]
    frame = log.dataframe[0].value
    assert list(frame.columns) == COLUMNS and len(frame) == len(LINES)
    assert frame["Event"].tolist() == [line["event"] for line in LINES]
    judge = frame.iloc[2]
    assert (judge["Time"], judge["Turn"], judge["Model"], judge["Prompt"]) == (
        "2026-11-13T10:15:00.963Z", "1", "google/gemini-3.8-flash", "judge@1")
    assert (judge["Latency ms"], judge["Tokens"], judge["Cost"]) == ("912", "698", "0.001047")
    assert frame.iloc[0]["Turn"] == "" and frame.iloc[0]["Model"] == ""   # blank where a line has no such field


def test_the_raw_json_of_every_line_is_shown_as_code(api):  # FR-012
    log = log_expander(opened(api))
    raw = log.code[0]
    assert raw.language == "json"
    assert [json.loads(text) for text in raw.value.splitlines()] == LINES


def test_a_send_failed_run_shows_its_failure_and_its_log(api):  # FR-012
    api["run"] = {**RUN_DETAIL, "failure_step": "endpoint_error", "verdict": None,
                  "failure_message": "The endpoint answered with an error.", "reply_text": None}
    at = opened(api)
    assert "The endpoint answered with an error." in [e.value for e in at.error]
    assert len(log_expander(at).dataframe[0].value) == len(LINES)


def test_a_run_without_kept_lines_says_so(api):  # FR-012, SC-003
    api["log"] = {"run_id": 7, "lines": [], "kept": 0, "dropped": 0, "truncated": False}
    log = log_expander(opened(api))
    assert [c.value for c in log.caption] == ["No log lines were recorded for this run."]
    assert len(log.dataframe) == 0 and len(log.code) == 0


def test_a_truncated_log_shows_the_marker_and_the_drop_count(api):  # FR-012
    marker = {"ts": "2026-11-13T10:15:09.000Z", "level": "WARNING", "logger": "kestrel", "event": "log.truncated",
              **SCOPE, "kept": 1000, "dropped": 3}
    api["log"] = {"run_id": 7, "lines": LINES + [marker], "kept": 1000, "dropped": 3, "truncated": True}
    log = log_expander(opened(api))
    assert "Log truncated: 3 line(s) were not kept after the first 1000." in [c.value for c in log.caption]
    assert log.dataframe[0].value["Event"].tolist()[-1] == "log.truncated"


def test_an_api_error_is_shown_like_the_rest_of_the_screen(api):  # FR-012
    api["log"] = api_client.ApiError(404, {"error": {"code": "not_found", "field": None,
                                                    "message": "No run with id 7."}})
    log = log_expander(opened(api))
    assert [e.value for e in log.error] == ["No run with id 7."]


def test_the_viewer_carries_no_known_string(api):  # FR-009, SC-002
    log = log_expander(opened(api))
    rendered = [log.dataframe[0].value.to_json(), *(c.value for c in log.code), *(c.value for c in log.caption)]
    for value in (SECRET, TARGET_URL, TARGET_NAME, ATTACK_TEXT, REPLY_TEXT):
        assert all(value not in text for text in rendered), value
