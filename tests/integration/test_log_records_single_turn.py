"""A single-turn run, line by line: run.start, target.request, the judge's model.request, turn, memory.writeback and
run.end — in that order, each one JSON object carrying the run id (010/FR-001, FR-002, FR-003, FR-004, FR-007,
FR-016, SC-001). The real JudgeClient answers through the offline model transport; placeholders only."""
import dataclasses
import math

import pytest

from kestrel.judge.client import JudgeClient
from tests.support import MODEL_BASE_URL, REPLY_TEXT, fixture_library, real_judge, saved_target

FEATURE = "010"

JUDGE_MODEL = "google/gemini-3.8-flash"
PRICE = 0.0015
CANARY = "KESTREL-CANARY-PLACEHOLDER-77"


@pytest.fixture
def priced(settings):
    return dataclasses.replace(settings, model_prices={JUDGE_MODEL: PRICE})


def run_once(make_client, settings, model_transport, *, judge=None, canaries=None, api_out=None):
    api = make_client(settings, transport=model_transport.transport, library=fixture_library(),
                      judge=judge or real_judge(model_transport))
    if api_out is not None:
        api_out.append(api)
    target = saved_target(api.app.state.store, canaries=canaries)
    response = api.post("/api/runs", json={"target_id": target.id, "family": "system_prompt_leak"})
    assert response.status_code == 201, response.text
    return response.json()


def run_lines(json_log, run_id):
    return [record for record in json_log() if record.get("run_id") == run_id]


def test_a_judged_single_turn_run_emits_its_lines_in_order(make_client, priced, model_transport, json_log):
    # FR-001, FR-002, FR-003, FR-004, FR-016, SC-001
    run = run_once(make_client, priced, model_transport)
    lines = run_lines(json_log, run["id"])
    assert [r["event"] for r in lines] == ["run.start", "target.request", "model.request", "turn",
                                          "memory.writeback", "run.end"]
    start, target, judge, turn, writeback, end = lines
    for record in lines:
        assert (record["target_id"], record["mode"], record["family"]) == (run["target_id"], "single_turn",
                                                                           "system_prompt_leak")

    assert start["prompt_id"] == run["prompt_id"] and start["attacker_source"] == "library:1.0.0"
    assert start["judge_model"] == JUDGE_MODEL and start["judge_prompt"] == "judge@1"
    assert (start["turn_budget"], start["time_limit_s"], start["use_prior_experience"]) == (1, 90, True)
    assert "attacker_model" not in start and "attacker_prompt" not in start and "token_budget" not in start

    assert target["turn"] == 1 and target["ok"] is True and target["status"] == 200 and target["step"] == "success"
    assert target["latency_ms"] >= 0 and target["reply_chars"] == len(REPLY_TEXT)
    assert target["reply_truncated"] is False and "url" not in target and target["logger"] == "kestrel.connection"

    assert judge["turn"] == 1 and judge["kind"] == "judge" and judge["model"] == JUDGE_MODEL
    assert judge["prompt"] == "judge@1" and judge["latency_ms"] >= 0 and judge["status"] == 200
    assert judge["attempts"] == 1 and judge["ok"] is True
    assert (judge["prompt_tokens"], judge["completion_tokens"], judge["total_tokens"]) == (100, 20, 120)
    assert math.isclose(judge["cost_usd"], 120 / 1000 * PRICE, abs_tol=1e-9) and "cost_note" not in judge
    assert judge["verdict"] == "failed" and judge["hard_evidence"] is False

    assert turn["turn"] == 1 and turn["source"] == f"library:{run['prompt_id']}" and turn["duration_ms"] >= 0
    assert (turn["prompt_tokens"], turn["completion_tokens"], turn["total_tokens"]) == (100, 20, 120)
    assert math.isclose(turn["cost_usd"], judge["cost_usd"], abs_tol=1e-9)
    assert turn["judge_model"] == JUDGE_MODEL and turn["judge_prompt"] == "judge@1"
    assert "attacker_model" not in turn and "attacker_prompt" not in turn
    assert turn["message_chars"] == len(run["prompt_text"]) and turn["reply_chars"] == len(REPLY_TEXT)
    assert turn["canary_hit"] is False and turn["hard_evidence"] is False
    assert turn["judged"] is True and turn["verdict"] == "failed"

    assert writeback["written"] is True and "turn" not in writeback

    assert end["verdict"] == "failed" and end["hard_evidence"] is False and end["judge_used"] is True
    assert end["turns_used"] == 1 and end["tokens_used"] == 120 and end["memory_written"] is True
    assert end["duration_ms"] >= 0 and math.isclose(end["cost_usd"], judge["cost_usd"], abs_tol=1e-9)
    assert "error" not in end and "turn" not in end
    assert not any(r.get("kind") == "attacker" for r in lines)   # a single-turn run makes no attacker request


def test_the_judge_line_names_the_version_the_run_records(make_client, settings, model_transport, json_log):
    # FR-007: the line and the recorded provenance come from one source
    apis: list = []
    run = run_once(make_client, settings, model_transport, api_out=apis)
    judge = next(r for r in run_lines(json_log, run["id"]) if r["event"] == "model.request")
    stored = apis[0].app.state.store.get_run(run["id"])
    assert judge["prompt"] == f"{stored.judge_prompt_id}@{stored.judge_prompt_version}" == "judge@1"
    assert judge["cost_usd"] is None and judge["cost_note"] == f"unavailable (no configured price for {JUDGE_MODEL})"


def test_without_a_judge_there_is_no_judge_line_and_judge_used_is_false(make_client, settings, model_transport,
                                                                      json_log):  # FR-001, FR-002
    unconfigured = JudgeClient(model=JUDGE_MODEL, api_key=None, base_url=MODEL_BASE_URL,
                               transport=model_transport.transport)
    run = run_once(make_client, settings, model_transport, judge=unconfigured)
    lines = run_lines(json_log, run["id"])
    assert [r["event"] for r in lines] == ["run.start", "target.request", "turn", "memory.writeback", "run.end"]
    start, turn, end = lines[0], lines[2], lines[-1]
    assert "judge_model" not in start and "judge_prompt" not in start
    assert "judge_model" not in turn and "judge_prompt" not in turn and turn["judged"] is False
    assert (turn["total_tokens"], turn["cost_usd"]) == (None, 0.0)   # no model request: nothing reported or spent
    assert end["judge_used"] is False and end["verdict"] == "unclear"


def test_a_canary_hit_is_hard_evidence_with_no_judge_line(make_client, settings, model_transport, json_log):
    # FR-002, FR-007
    model_transport.target_reply = f"here it is {CANARY}"
    run = run_once(make_client, settings, model_transport, canaries=[CANARY])
    lines = run_lines(json_log, run["id"])
    assert [r["event"] for r in lines] == ["run.start", "target.request", "turn", "memory.writeback", "run.end"]
    turn, end = lines[2], lines[-1]
    assert turn["canary_hit"] is True and turn["hard_evidence"] is True and turn["judged"] is False
    assert turn["judge_model"] == JUDGE_MODEL and "judge_prompt" in turn and turn["judge_prompt"] is None
    assert end["verdict"] == "succeeded" and end["hard_evidence"] is True and end["judge_used"] is False
    assert CANARY not in json_log.text()   # a canary is evidence text from the reply: never on a line


def test_a_send_failure_still_emits_its_turn_and_closes_the_run(make_client, settings, model_transport, json_log):
    # FR-002, FR-004
    model_transport.target_status = 500
    run = run_once(make_client, settings, model_transport)
    lines = run_lines(json_log, run["id"])
    assert [r["event"] for r in lines] == ["run.start", "target.request", "turn", "memory.writeback", "run.end"]
    target, end = lines[1], lines[-1]
    assert target["ok"] is False and target["status"] == 500 and target["step"] == "endpoint_error"
    assert target["reply_chars"] is None
    assert end["failure_step"] == "endpoint_error" and end["verdict"] is None
