"""A replay's own log lines, through the real structured-event stream (012/FR-043, FR-045, FR-047, SC-008)."""
from __future__ import annotations

from tests.support import (JUDGE_PROGRESS, JUDGE_REASON, REPLY_TEXT, SECRET, TARGET_NAME, TARGET_URL, real_attacker,
                           real_judge, saved_target)

FEATURE = "012"

MARKERS = (SECRET, TARGET_URL, TARGET_NAME, REPLY_TEXT, JUDGE_REASON, JUDGE_PROGRESS)

CLAIM = dict(prompt_id="spl-001", prompt_title="t", prompt_text="<seed>", family="system_prompt_leak",
            owasp_category="LLM07: System Prompt Leakage", attacker_source="library:1.0.0")


def run_attack(client, target_id: int, *, mode: str = "single_turn") -> dict:
    response = client.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak", "mode": mode})
    assert response.status_code == 201, response.text
    return response.json()


def claim_adaptive_source(store, target_id: int, *, turns: int) -> int:
    """A finished, succeeded adaptive run with `turns` recorded turns, built directly so its shape (and turn
    count) is exact, regardless of how the real judge/attacker doubles would otherwise behave turn by turn."""
    run_id = store.claim_run(target_id, mode="adaptive", attacker_model="a/m", turn_budget=6, token_budget=40000,
                             time_limit_s=300, **CLAIM)
    for position in range(1, turns + 1):
        store.add_turn(run_id, position=position, attacker_message=f"<turn {position}>", reply_text="<reply>",
                       judge_verdict="failed")
    store.finish_run(run_id, verdict="succeeded", hard_evidence=False, judge_used=True, judge_model="j/m",
                     stopping_condition="succeeded", succeeded_turn=turns, turns_used=turns)
    return run_id


def lines_for(json_log, run_id: int) -> list[dict]:
    return [line for line in json_log() if line.get("run_id") == run_id]


def test_run_start_carries_source_run_id_and_mode_replay(make_client, model_transport, json_log):
    model_transport.verdict = "succeeded"
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    target = saved_target(client.app.state.store, url=TARGET_URL, name=TARGET_NAME)
    source = run_attack(client, target.id)

    model_transport.verdict = "failed"
    replay = client.post(f"/api/runs/{source['id']}/replay").json()

    start = next(line for line in lines_for(json_log, replay["id"]) if line["event"] == "run.start")
    assert start["mode"] == "replay" and start["source_run_id"] == source["id"]


def test_no_attacker_model_request_line_and_no_memory_lines_anywhere(make_client, model_transport, json_log):
    model_transport.verdict = "succeeded"
    attacker = real_attacker(model_transport)
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport), attacker=attacker)
    target = saved_target(client.app.state.store, url=TARGET_URL, name=TARGET_NAME)
    source = run_attack(client, target.id, mode="adaptive")

    model_transport.verdict = "failed"
    replay = client.post(f"/api/runs/{source['id']}/replay").json()

    replay_lines = lines_for(json_log, replay["id"])
    assert [line for line in replay_lines if line["event"] == "model.request" and line.get("kind") == "attacker"] == []
    assert [line for line in replay_lines if line["event"] == "memory.retrieval"] == []
    assert [line for line in replay_lines if line["event"] == "memory.writeback"] == []
    assert next(line for line in replay_lines if line["event"] == "run.end")["memory_written"] is None


def test_every_turn_of_an_adaptive_replay_omits_attacker_fields_even_turn_two_onward(make_client, model_transport,
                                                                                      json_log):
    """A normal adaptive run's turn 2+ carries attacker_model/attacker_prompt (attacker_generated=True,
    `tests/integration/test_log_records_adaptive.py` proves it); a replay's every turn, including what would be
    turn 2+, never does - no attacker ever runs."""
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL, name=TARGET_NAME)
    source_id = claim_adaptive_source(store, target.id, turns=2)

    model_transport.verdict = "failed"
    replay = client.post(f"/api/runs/{source_id}/replay").json()

    replay_lines = lines_for(json_log, replay["id"])
    replay_turn_two = next(line for line in replay_lines if line["event"] == "turn" and line["turn"] == 2)
    assert "attacker_model" not in replay_turn_two and "attacker_prompt" not in replay_turn_two


def test_a_replays_turn_lines_still_carry_duration_and_token_fields(make_client, model_transport, json_log):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL, name=TARGET_NAME)
    source_id = claim_adaptive_source(store, target.id, turns=2)

    model_transport.verdict = "failed"
    replay = client.post(f"/api/runs/{source_id}/replay").json()

    turn_lines = [line for line in lines_for(json_log, replay["id"]) if line["event"] == "turn"]
    assert [line["turn"] for line in turn_lines] == list(range(1, len(turn_lines) + 1))
    for line in turn_lines:
        assert line["duration_ms"] >= 0
        if line["judged"]:
            assert line["prompt_tokens"] is not None and line["completion_tokens"] is not None
            assert line["total_tokens"] is not None


def test_run_end_carries_replay_outcome_only_for_the_replay_never_for_the_source(make_client, model_transport,
                                                                                  json_log):
    model_transport.verdict = "succeeded"
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    target = saved_target(client.app.state.store, url=TARGET_URL, name=TARGET_NAME)
    source = run_attack(client, target.id)

    model_transport.verdict = "failed"
    replay = client.post(f"/api/runs/{source['id']}/replay").json()

    source_end = next(line for line in lines_for(json_log, source["id"]) if line["event"] == "run.end")
    assert "replay_outcome" not in source_end

    replay_end = next(line for line in lines_for(json_log, replay["id"]) if line["event"] == "run.end")
    assert replay_end["replay_outcome"] == "fixed"


def test_no_secret_url_name_or_free_text_appears_anywhere_in_the_stream(make_client, model_transport, json_log):
    model_transport.verdict = "succeeded"
    attacker = real_attacker(model_transport)
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport), attacker=attacker)
    target = saved_target(client.app.state.store, url=TARGET_URL, name=TARGET_NAME)
    source = run_attack(client, target.id, mode="adaptive")

    model_transport.verdict = "failed"
    client.post(f"/api/runs/{source['id']}/replay")

    text = json_log.text()
    for marker in MARKERS:
        assert marker not in text, marker
