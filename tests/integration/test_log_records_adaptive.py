"""An adaptive run, line by line: one turn line per turn with its own totals, one attacker and one judge
model.request per call, one target.request per send, retrieval lines from turn 2 of a warm run, the write-back
before run.end (010/FR-002, FR-003, FR-004, FR-016, SC-001). The real AttackerClient and JudgeClient answer
through the offline model transport; placeholders only."""
import dataclasses

import pytest

from kestrel.judge.client import JudgeClient
from tests.support import ATTACK_TEXT, MODEL_BASE_URL, fixture_library, real_attacker, real_judge, saved_target

FEATURE = "010"

ATTACKER_MODEL = "deepseek/deepseek-v4.1-flash"
JUDGE_MODEL = "google/gemini-3.8-flash"
ATTACKER_PROMPT = "attacker:system_prompt_leak@1"


@pytest.fixture
def three_turns(settings):
    return dataclasses.replace(settings, adaptive_max_turns=3)


def adaptive_run(make_client, settings, model_transport, *, judge=None, empty_store=False, **body):
    api = make_client(settings, transport=model_transport.transport, library=fixture_library(),
                      judge=judge or real_judge(model_transport), attacker=real_attacker(model_transport))
    if empty_store:   # a cold store: no pattern to retrieve
        api.app.state.experience._collection.delete(where={"type": "pattern"})
    target = saved_target(api.app.state.store)
    response = api.post("/api/runs", json={"target_id": target.id, "family": "system_prompt_leak",
                                           "mode": "adaptive", **body})
    assert response.status_code == 201, response.text
    return response.json()


def run_lines(json_log, run_id):
    return [record for record in json_log() if record.get("run_id") == run_id]


def of(lines, event, **match):
    return [r for r in lines if r["event"] == event and all(r.get(k) == v for k, v in match.items())]


def test_one_turn_line_per_turn_with_that_turns_totals(make_client, three_turns, model_transport, json_log):
    # FR-002, FR-003, FR-004, SC-001
    run = adaptive_run(make_client, three_turns, model_transport)
    lines = run_lines(json_log, run["id"])
    assert run["turns_used"] == 3 and lines[0]["event"] == "run.start" and lines[-1]["event"] == "run.end"
    turns = of(lines, "turn")
    assert [t["turn"] for t in turns] == [1, 2, 3]
    assert (turns[0]["prompt_tokens"], turns[0]["completion_tokens"], turns[0]["total_tokens"]) == (100, 20, 120)
    for turn in turns[1:]:   # the attacker's request and the judge's, summed for that turn alone
        assert (turn["prompt_tokens"], turn["completion_tokens"], turn["total_tokens"]) == (200, 40, 240)
    for turn in turns:
        assert turn["duration_ms"] >= 0 and turn["judge_model"] == JUDGE_MODEL and turn["judge_prompt"] == "judge@1"
        assert turn["judged"] is True and turn["verdict"] == "failed" and turn["message_chars"] > 0
        assert turn["cost_usd"] is None and turn["cost_note"].startswith("unavailable (no configured price for ")
    assert turns[0]["source"] == f"library:{run['prompt_id']}" and "attacker_model" not in turns[0]
    for turn in turns[1:]:
        assert turn["source"] == ATTACKER_PROMPT and turn["attacker_model"] == ATTACKER_MODEL
        assert turn["attacker_prompt"] == ATTACKER_PROMPT and turn["message_chars"] == len(ATTACK_TEXT)

    attackers = of(lines, "model.request", kind="attacker")
    assert [a["turn"] for a in attackers] == [2, 3]
    assert all(a["prompt"] == ATTACKER_PROMPT and a["message_chars"] == len(ATTACK_TEXT) and a["ok"] for a in attackers)
    assert [j["turn"] for j in of(lines, "model.request", kind="judge")] == [1, 2, 3]
    assert [t["turn"] for t in of(lines, "target.request")] == [1, 2, 3]

    order = [r["event"] for r in lines if r.get("turn") == 2]   # a turn's own order (contracts: ordering guarantees)
    assert order == ["memory.retrieval", "model.request", "target.request", "model.request", "turn"]
    end = lines[-1]
    assert [r["event"] for r in lines[-2:]] == ["memory.writeback", "run.end"]
    assert end["judge_used"] is True and end["turns_used"] == 3 and end["stopping_condition"] == "turn_cap"
    assert end["tokens_used"] == run["tokens_used"] == 120 + 240 + 240 and end["memory_written"] is True


def test_a_warm_run_logs_retrieval_from_turn_2_with_the_pattern_ids(make_client, three_turns, model_transport,
                                                                    json_log):  # FR-016
    run = adaptive_run(make_client, three_turns, model_transport)
    retrievals = of(run_lines(json_log, run["id"]), "memory.retrieval")
    assert [r["turn"] for r in retrievals] == [2, 3]   # turn 1 sends the library seed and never asks
    for retrieval in retrievals:
        assert retrieval["warm"] is True and retrieval["pattern_count"] == len(retrieval["pattern_ids"]) > 0
        assert all(pid.startswith("pattern:lib:spl-") for pid in retrieval["pattern_ids"])
        assert retrieval["memory_count"] == 0


def test_a_cold_store_still_logs_retrieval_with_zero_counts(make_client, three_turns, model_transport, json_log):
    # FR-016
    run = adaptive_run(make_client, three_turns, model_transport, empty_store=True)
    retrievals = of(run_lines(json_log, run["id"]), "memory.retrieval")
    assert len(retrievals) == 2
    assert all((r["warm"], r["pattern_count"], r["memory_count"], r["pattern_ids"]) == (False, 0, 0, [])
               for r in retrievals)


def test_prior_experience_off_asks_for_nothing(make_client, three_turns, model_transport, json_log):  # FR-016
    run = adaptive_run(make_client, three_turns, model_transport, use_prior_experience=False)
    lines = run_lines(json_log, run["id"])
    assert of(lines, "memory.retrieval") == [] and lines[0]["use_prior_experience"] is False


def test_without_a_judge_no_judge_line_and_no_judge_fields(make_client, three_turns, model_transport, json_log):
    # FR-002, FR-003
    unconfigured = JudgeClient(model=JUDGE_MODEL, api_key=None, base_url=MODEL_BASE_URL,
                               transport=model_transport.transport)
    run = adaptive_run(make_client, three_turns, model_transport, judge=unconfigured)
    lines = run_lines(json_log, run["id"])
    assert of(lines, "model.request", kind="judge") == []
    assert "judge_model" not in lines[0] and "judge_prompt" not in lines[0]
    assert all("judge_model" not in t and "judge_prompt" not in t for t in of(lines, "turn"))
    assert lines[-1]["judge_used"] is False


def test_an_attacker_failure_is_one_failed_line_and_the_run_ends_attacker_failed(make_client, three_turns,
                                                                                 model_transport, json_log):
    # FR-003, edge case: the attacker fails
    model_transport.attacker_statuses = [400]
    run = adaptive_run(make_client, three_turns, model_transport)
    lines = run_lines(json_log, run["id"])
    failed = of(lines, "model.request", kind="attacker")
    assert len(failed) == 1 and failed[0]["ok"] is False and failed[0]["error"] == "AttackerError"
    assert failed[0]["status"] == 400 and failed[0]["level"] == "ERROR" and failed[0]["turn"] == 2
    assert (failed[0]["prompt_tokens"], failed[0]["completion_tokens"], failed[0]["total_tokens"]) == (None,) * 3
    assert failed[0]["cost_usd"] is None and failed[0]["cost_note"] == "no usage reported by the provider"
    assert "placeholder provider error" not in json_log.text()
    assert lines[-1]["event"] == "run.end" and lines[-1]["stopping_condition"] == "attacker_failed"
    assert [t["turn"] for t in of(lines, "turn")] == [1]


def test_a_retried_request_is_one_line_with_its_attempts_and_summed_tokens(make_client, three_turns, model_transport,
                                                                           json_log):  # FR-003
    model_transport.attacker_statuses = [503, 200]
    model_transport.error_usage = {"prompt_tokens": 5, "completion_tokens": 0, "total_tokens": 5}
    run = adaptive_run(make_client, three_turns, model_transport)
    attacker = of(run_lines(json_log, run["id"]), "model.request", kind="attacker")[0]
    assert attacker["attempts"] == 2 and attacker["ok"] is True and attacker["status"] == 200
    assert (attacker["prompt_tokens"], attacker["completion_tokens"], attacker["total_tokens"]) == (105, 20, 125)
