"""`POST /api/targets/{target_id}/replays`: oldest-first ordering, the configured cap, an honest incomplete
result when the batch cannot finish (012/FR-028 to FR-033, SC-006)."""
from __future__ import annotations

import dataclasses

from tests.support import TARGET_URL, real_judge, saved_target

FEATURE = "012"

CLAIM = dict(prompt_id="spl-001", prompt_title="t", prompt_text="<seed>", family="system_prompt_leak",
            owasp_category="LLM07: System Prompt Leakage", attacker_source="library:1.0.0")


def claim_succeeded_single_turn(store, target_id: int, *, canary_hit: bool = True) -> int:
    run_id = store.claim_run(target_id, **CLAIM)
    store.finish_run(run_id, verdict="succeeded", hard_evidence=canary_hit, judge_used=not canary_hit,
                     judge_model=None if canary_hit else "j/m")
    return run_id


def claim_adaptive_source(store, target_id: int, *, turns: int = 2) -> int:
    run_id = store.claim_run(target_id, mode="adaptive", attacker_model="a/m", turn_budget=6, token_budget=40000,
                             time_limit_s=300, **CLAIM)
    for position in range(1, turns + 1):
        store.add_turn(run_id, position=position, attacker_message=f"<turn {position}>", reply_text="<reply>",
                       judge_verdict="failed")
    store.finish_run(run_id, verdict="succeeded", hard_evidence=False, judge_used=True, judge_model="j/m",
                     stopping_condition="succeeded", succeeded_turn=turns, turns_used=turns)
    return run_id


def test_a_batch_processes_only_the_replayable_runs_oldest_first(make_client, model_transport):
    # FR-030: exactly one entry per processed source, naming both runs, the family, both verdicts and evidence
    # kinds, and the computed outcome; counts sum to the entry count.
    model_transport.verdict = "failed"
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)

    oldest = claim_succeeded_single_turn(store, target.id, canary_hit=True)
    middle = claim_adaptive_source(store, target.id, turns=2)
    newest = claim_succeeded_single_turn(store, target.id, canary_hit=False)
    # Not replayable, and crucially all FINISHED: a genuinely open run would itself trip the batch's own
    # upfront "another run already in progress" precondition (FR-029) and refuse the whole batch - that case is
    # covered separately (test_list_replayable_runs_is_unaffected_by_a_concurrent_in_progress_run,
    # tests/unit/test_replay_eligibility.py), which checks list_replayable_runs directly, beneath that
    # precondition. An interrupted (now "unclear") run exercises the same "not succeeded" exclusion safely here.
    interrupted = store.claim_run(target.id, prompt_id="spl-002", prompt_title="t2", prompt_text="<seed2>",
                                  family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                                  attacker_source="library:1.0.0")
    store.close_interrupted_runs()
    assert store.get_run(interrupted).verdict == "unclear"
    failed = store.claim_run(target.id, prompt_id="spl-003", prompt_title="t3", prompt_text="<seed3>",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0")
    store.finish_run(failed, verdict="failed")
    replay_mode = store.claim_run(target.id, mode="replay", source_run_id=oldest, **{**CLAIM, "prompt_id": "spl-004"})
    store.finish_run(replay_mode, verdict="succeeded", replay_outcome="still_vulnerable")

    response = client.post(f"/api/targets/{target.id}/replays")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [e["source_run_id"] for e in body["entries"]] == [oldest, middle, newest]
    assert "source_hard_evidence" in body["entries"][0] and "replay_hard_evidence" in body["entries"][0]
    assert sum(body["counts"].values()) == len(body["entries"]) == 3
    assert body["complete"] is True and body["stop_reason"] is None and body["not_replayed_source_ids"] == []
    assert body["failed_source_run_id"] is None


def test_a_target_with_zero_replayable_runs_completes_trivially(client):
    target = saved_target(client.app.state.store, url=TARGET_URL)

    response = client.post(f"/api/targets/{target.id}/replays")

    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == [] and body["complete"] is True
    assert body["counts"] == {"fixed": 0, "still_vulnerable": 0, "inconclusive": 0}


def test_an_unknown_target_404s_a_batch_replay(client):  # FR-029
    response = client.post("/api/targets/999/replays")
    assert response.status_code == 404


def test_permission_missing_refuses_the_whole_batch(make_client, model_transport):  # FR-006, FR-029
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    claim_succeeded_single_turn(store, target.id)
    with store.connect() as db:
        db.execute("UPDATE targets SET permission_confirmed_at = '' WHERE id = ?", (target.id,))

    response = client.post(f"/api/targets/{target.id}/replays")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "permission_missing"
    assert error["message"] == "Tick the permission box and save the target before attacking it."


def test_terms_outdated_refuses_the_whole_batch(make_client, model_transport):  # FR-006, FR-029
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    claim_succeeded_single_turn(store, target.id)
    with store.connect() as db:
        db.execute("UPDATE targets SET terms_version = 'old' WHERE id = ?", (target.id,))

    response = client.post(f"/api/targets/{target.id}/replays")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "terms_outdated"
    assert error["message"] == "The terms of service have changed; read them and tick the box again."


def test_a_target_over_the_configured_cap_refuses_the_whole_batch_before_sending_anything(make_client, settings,
                                                                                            model_transport):
    lowered = dataclasses.replace(settings, replay_batch_max_runs=2)
    client = make_client(lowered, transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    for _ in range(3):
        claim_succeeded_single_turn(store, target.id)
    before = len(store.list_runs(target.id))

    response = client.post(f"/api/targets/{target.id}/replays")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "batch_too_large"
    assert "3" in error["message"] and "2" in error["message"]
    assert len(store.list_runs(target.id)) == before   # nothing was claimed


def test_an_experiment_produced_run_counts_toward_the_cap_and_is_replayed(make_client, model_transport):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    source = claim_succeeded_single_turn(store, target.id)
    # Tag it as an experiment-produced run (feature 007): an ordinary run of its target, replayable like any
    # other (spec.md Edge Cases).
    experiment_id = store.create_experiment(
        target_id=target.id, mode="single_turn", families=["system_prompt_leak"], reps=1,
        seed_prompt_ids={"system_prompt_leak": "spl-001"}, max_runs=1, token_budget_total=1000, wall_clock_s=60,
        arm_a={"attacker_model": "a/m", "judge_model": "j/m", "use_prior_experience": False, "turn_cap": 1,
              "token_budget": 1000},
        arm_b={"attacker_model": "a/m", "judge_model": "j/m", "use_prior_experience": True, "turn_cap": 1,
              "token_budget": 1000}).id
    arm_id = store.get_experiment(experiment_id).arms[0].id
    store.add_experiment_run(experiment_id=experiment_id, arm_id=arm_id, rep_index=0, family="system_prompt_leak",
                             run_id=source)

    response = client.post(f"/api/targets/{target.id}/replays")

    assert response.status_code == 200
    assert [e["source_run_id"] for e in response.json()["entries"]] == [source]


def test_a_mid_batch_collision_stops_the_batch_at_200_never_409(make_client, model_transport, monkeypatch):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    sources = [claim_succeeded_single_turn(store, target.id) for _ in range(3)]

    import kestrel.replay as replay_module
    real_execute_replay = replay_module.execute_replay
    calls = {"n": 0}

    async def colliding_execute_replay(store_arg, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            # A genuinely concurrent run starts on the same target partway through the batch (another browser
            # tab, or the CI script and a user acting at the same moment).
            store.claim_run(target.id, prompt_id="spl-999", prompt_title="x", prompt_text="<x>",
                            family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                            attacker_source="library:1.0.0")
        return await real_execute_replay(store_arg, **kwargs)

    monkeypatch.setattr(replay_module, "execute_replay", colliding_execute_replay)

    response = client.post(f"/api/targets/{target.id}/replays")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["complete"] is False and body["stop_reason"] == "run_in_progress"
    assert [e["source_run_id"] for e in body["entries"]] == [sources[0]]
    assert body["not_replayed_source_ids"] == sources[1:]
    assert body["failed_source_run_id"] is None   # a collision, never a replay failure (review item 5)


def test_one_entrys_own_replay_failure_is_included_inconclusive_and_the_batch_stops(make_client, model_transport):
    """A sender-level fault on the second source's own send (not a RunInProgress collision): execute_replay's
    ReplayFailed path closes that entry's row inconclusive, and the batch stops there, never a 500."""
    import httpx

    from tests.support import MODEL_BASE_URL

    target_calls = {"n": 0}

    def exploding_handle(request: httpx.Request) -> httpx.Response:
        if request.url.host != httpx.URL(MODEL_BASE_URL).host:   # a target request, not a model one
            target_calls["n"] += 1
            if target_calls["n"] == 2:
                raise RuntimeError("simulated target failure")
        return model_transport.handle(request)

    client = make_client(transport=httpx.MockTransport(exploding_handle), judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    sources = [claim_succeeded_single_turn(store, target.id) for _ in range(3)]

    response = client.post(f"/api/targets/{target.id}/replays")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["complete"] is False and body["stop_reason"] == "replay_failed"
    assert [e["source_run_id"] for e in body["entries"]] == sources[:2]
    assert body["entries"][1]["outcome"] == "inconclusive"
    assert body["entries"][1]["replay_verdict"] == "unclear"
    assert body["not_replayed_source_ids"] == sources[2:]
    assert body["failed_source_run_id"] == sources[1]   # after the claim: the crashed source has its own entry


def test_a_fault_before_any_row_is_claimed_adds_no_entry_for_that_source(make_client, model_transport, monkeypatch):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    sources = [claim_succeeded_single_turn(store, target.id) for _ in range(2)]

    original_claim_run = store.claim_run
    calls = {"n": 0}

    def exploding_claim_run(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:   # the batch's own first claim, inside execute_replay for the first source
            raise RuntimeError("simulated claim failure")
        return original_claim_run(*args, **kwargs)

    monkeypatch.setattr(store, "claim_run", exploding_claim_run)

    response = client.post(f"/api/targets/{target.id}/replays")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["complete"] is False and body["stop_reason"] == "replay_failed"
    assert body["entries"] == []
    assert body["not_replayed_source_ids"] == sources
    assert body["failed_source_run_id"] == sources[0]   # before the claim: no entry of its own was ever added


def test_a_fault_before_claim_on_a_later_source_never_blames_the_prior_clean_entry(make_client, model_transport,
                                                                                   monkeypatch):
    """The real defect the review caught (item 5): a before-claim failure on the SECOND source adds no entry for
    it, but the first source's own entry - cleanly judged, judged with real evidence - sits last in the list. A
    reader that assumed "the last entry is always the crashed one" would misattribute the clean entry."""
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    sources = [claim_succeeded_single_turn(store, target.id) for _ in range(2)]

    original_claim_run = store.claim_run
    calls = {"n": 0}

    def exploding_claim_run(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:   # the batch's second claim, inside execute_replay for the second source
            raise RuntimeError("simulated claim failure")
        return original_claim_run(*args, **kwargs)

    monkeypatch.setattr(store, "claim_run", exploding_claim_run)

    response = client.post(f"/api/targets/{target.id}/replays")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["complete"] is False and body["stop_reason"] == "replay_failed"
    assert [e["source_run_id"] for e in body["entries"]] == [sources[0]]   # the first source's own clean entry
    assert body["failed_source_run_id"] == sources[1]   # never sources[0], whose entry is unrelated
    assert body["not_replayed_source_ids"] == sources[1:]


def test_a_failure_between_the_claim_and_the_try_is_recorded_as_an_entry_not_lost(make_client, model_transport,
                                                                                   monkeypatch):
    """The residual (review round 2, item 1): a failure after a batch entry's own claim but before its own try
    (judge_ref, building or compiling the graph) must be treated as an after-claim failure, not a before-claim
    one - the batch records an entry for it, inconclusive, failed_source_run_id names it, and the target is not
    left locked once the batch request returns."""
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    sources = [claim_succeeded_single_turn(store, target.id) for _ in range(2)]

    import kestrel.replay as replay_module
    original_judge_ref = replay_module.judge_ref
    calls = {"n": 0}

    def exploding_judge_ref(judge):
        calls["n"] += 1
        if calls["n"] == 1:   # the first entry's own judge_ref call, after its claim
            raise RuntimeError("simulated judge_ref failure")
        return original_judge_ref(judge)

    monkeypatch.setattr(replay_module, "judge_ref", exploding_judge_ref)

    response = client.post(f"/api/targets/{target.id}/replays")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["complete"] is False and body["stop_reason"] == "replay_failed"
    assert [e["source_run_id"] for e in body["entries"]] == [sources[0]]
    assert body["entries"][0]["outcome"] == "inconclusive"
    assert body["failed_source_run_id"] == sources[0]
    assert body["not_replayed_source_ids"] == sources[1:]

    # The target is not locked: a new run can be claimed immediately.
    new_run_id = store.claim_run(target.id, prompt_id="spl-999", prompt_title="x", prompt_text="<x>",
                                 family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                                 attacker_source="library:1.0.0")
    assert new_run_id is not None
