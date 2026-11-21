"""A replay's own log lines, through the real structured-event stream (012/FR-043, FR-045, FR-047, SC-008)."""
from __future__ import annotations

import httpx
import pytest

from kestrel.replay import ReplayFailed
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


def claim_succeeded_single_turn(store, target_id: int, *, prompt_id: str = "spl-001") -> int:
    run_id = store.claim_run(target_id, **{**CLAIM, "prompt_id": prompt_id})
    store.finish_run(run_id, verdict="succeeded", hard_evidence=True)
    return run_id


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


def test_run_end_names_the_root_cause_class_not_replayfailed(make_client, model_transport, json_log):
    """An unexpected failure during a replay's own send must log run.end's error as the ORIGINAL exception's
    class, never the ReplayFailed wrapper that carries it up to the caller (review item 8)."""
    def exploding_handle(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("simulated target failure")

    client = make_client(transport=httpx.MockTransport(exploding_handle), judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL, name=TARGET_NAME)
    source = claim_succeeded_single_turn(store, target.id)

    with pytest.raises(ReplayFailed):
        client.post(f"/api/runs/{source}/replay")

    replay_end = next(line for line in json_log() if line["event"] == "run.end" and line.get("mode") == "replay")
    assert replay_end["error"] == "RuntimeError"


# ---- the batch replay's own lines (T029; 012/FR-029, FR-043, FR-044, FR-045) ----


def test_a_complete_batch_emits_one_start_and_one_end_line_around_every_entrys_own_pair(make_client,
                                                                                          model_transport, json_log):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL, name=TARGET_NAME)
    first = claim_succeeded_single_turn(store, target.id, prompt_id="spl-001")
    second = claim_succeeded_single_turn(store, target.id, prompt_id="spl-002")

    model_transport.verdict = "failed"
    response = client.post(f"/api/targets/{target.id}/replays")
    assert response.status_code == 200, response.text
    replay_ids = [e["replay_run_id"] for e in response.json()["entries"]]

    events = json_log.events()
    start = next(i for i, e in enumerate(events) if e == "replay.batch.start")
    end = next(i for i, e in enumerate(events) if e == "replay.batch.end")
    assert events.count("replay.batch.start") == 1 and events.count("replay.batch.end") == 1
    assert start < end

    batch_start = json_log.of("replay.batch.start")[0]
    assert batch_start["target_id"] == target.id and batch_start["replayable_count"] == 2 and batch_start["cap"] == 20

    batch_end = json_log.of("replay.batch.end")[0]
    assert batch_end["fixed_count"] == 2 and batch_end["still_vulnerable_count"] == 0
    assert batch_end["inconclusive_count"] == 0 and batch_end["complete"] is True
    assert "stop_reason" not in batch_end and "error" not in batch_end

    # Every entry's own run.start/run.end sits strictly between the batch's one start and end line - never
    # replacing them - and each still carries what a replay's own scope always does (source_run_id, mode,
    # its own replay_outcome).
    lines = json_log()
    for source_id, replay_id in ((first, replay_ids[0]), (second, replay_ids[1])):
        entry_start = next(i for i, line in enumerate(lines)
                           if line["event"] == "run.start" and line.get("run_id") == replay_id)
        entry_end = next(i for i, line in enumerate(lines)
                         if line["event"] == "run.end" and line.get("run_id") == replay_id)
        assert start < entry_start < entry_end < end
        assert lines[entry_start]["mode"] == "replay" and lines[entry_start]["source_run_id"] == source_id
        assert lines[entry_end]["replay_outcome"] == "fixed"


def test_a_batch_refused_before_it_starts_emits_neither_line(make_client, settings, model_transport, json_log):
    import dataclasses
    lowered = dataclasses.replace(settings, replay_batch_max_runs=1)
    client = make_client(lowered, transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL, name=TARGET_NAME)
    claim_succeeded_single_turn(store, target.id, prompt_id="spl-001")
    claim_succeeded_single_turn(store, target.id, prompt_id="spl-002")

    response = client.post(f"/api/targets/{target.id}/replays")

    assert response.status_code == 409 and response.json()["error"]["code"] == "batch_too_large"
    assert "replay.batch.start" not in json_log.events() and "replay.batch.end" not in json_log.events()


def test_a_mid_batch_collision_ends_the_batch_line_incomplete_with_no_error(make_client, model_transport, json_log,
                                                                              monkeypatch):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL, name=TARGET_NAME)
    claim_succeeded_single_turn(store, target.id, prompt_id="spl-001")
    claim_succeeded_single_turn(store, target.id, prompt_id="spl-002")

    import kestrel.replay as replay_module
    real_execute_replay = replay_module.execute_replay
    calls = {"n": 0}

    async def colliding_execute_replay(store_arg, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            store.claim_run(target.id, prompt_id="spl-999", prompt_title="x", prompt_text="<x>",
                            family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                            attacker_source="library:1.0.0")
        return await real_execute_replay(store_arg, **kwargs)

    monkeypatch.setattr(replay_module, "execute_replay", colliding_execute_replay)

    response = client.post(f"/api/targets/{target.id}/replays")

    assert response.status_code == 200, response.text
    batch_end = json_log.of("replay.batch.end")[0]
    assert batch_end["complete"] is False and batch_end["stop_reason"] == "run_in_progress"
    assert "error" not in batch_end   # a collision is an expected stop, not a failure (research D17)


def test_one_entrys_own_failure_ends_the_batch_line_with_the_root_cause_class(make_client, model_transport,
                                                                               json_log):
    """The entry's own run.end already names the real class (review item 8); the batch's own end line carries it
    too, raising the line to ERROR - never the ReplayFailed wrapper's name, and never set at all for a
    run_in_progress collision (that stays an expected stop, test_a_mid_batch_collision... above)."""
    from tests.support import MODEL_BASE_URL

    target_calls = {"n": 0}

    def exploding_handle(request: httpx.Request) -> httpx.Response:
        if request.url.host != httpx.URL(MODEL_BASE_URL).host:
            target_calls["n"] += 1
            if target_calls["n"] == 2:
                raise RuntimeError("simulated target failure")
        return model_transport.handle(request)

    client = make_client(transport=httpx.MockTransport(exploding_handle), judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL, name=TARGET_NAME)
    claim_succeeded_single_turn(store, target.id, prompt_id="spl-001")
    claim_succeeded_single_turn(store, target.id, prompt_id="spl-002")

    response = client.post(f"/api/targets/{target.id}/replays")

    assert response.status_code == 200, response.text
    batch_end = json_log.of("replay.batch.end")[0]
    assert batch_end["complete"] is False and batch_end["stop_reason"] == "replay_failed"
    assert batch_end["error"] == "RuntimeError"
    assert batch_end["level"] == "ERROR"


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
