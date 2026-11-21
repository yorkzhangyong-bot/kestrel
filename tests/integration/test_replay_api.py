"""`POST /api/runs/{run_id}/replay`'s shapes and error codes (contracts/api.md; 012/FR-004 to FR-006, FR-017,
FR-027, FR-038 to FR-042, SC-005)."""
from __future__ import annotations

import dataclasses

from tests.support import TARGET_URL, real_judge, saved_target

FEATURE = "012"

CLAIM = dict(prompt_id="spl-001", prompt_title="t", prompt_text="<seed>", family="system_prompt_leak",
            owasp_category="LLM07: System Prompt Leakage", attacker_source="library:1.0.0")


def run_attack(client, target_id: int) -> dict:
    response = client.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                               "mode": "single_turn"})
    assert response.status_code == 201, response.text
    return response.json()


def claim_adaptive_source(store, target_id: int, *, turns: list[str], succeeded_turn: int) -> int:
    """A finished, succeeded adaptive run with `turns` recorded turns, built directly (not through the live
    loop), so the API tests below control its shape precisely."""
    run_id = store.claim_run(target_id, mode="adaptive", attacker_model="a/m", turn_budget=6, token_budget=40000,
                             time_limit_s=300, **CLAIM)
    for position, verdict in enumerate(turns, start=1):
        store.add_turn(run_id, position=position, attacker_message=f"<turn {position}>", reply_text="<reply>",
                       judge_verdict=verdict)
    store.finish_run(run_id, verdict="succeeded", hard_evidence=False, judge_used=True, judge_model="j/m",
                     stopping_condition="succeeded", succeeded_turn=succeeded_turn, turns_used=len(turns))
    return run_id


def test_replaying_an_eligible_run_returns_201_with_a_comparison(make_client, model_transport):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    target = saved_target(client.app.state.store, url=TARGET_URL)
    model_transport.verdict = "succeeded"
    source = run_attack(client, target.id)
    assert source["verdict"] == "succeeded"

    model_transport.verdict = "failed"
    response = client.post(f"/api/runs/{source['id']}/replay")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["mode"] == "replay" and body["source_run_id"] == source["id"]
    assert body["comparison"] is not None
    assert body["comparison"]["source_run_id"] == source["id"] and body["comparison"]["replay_run_id"] == body["id"]
    assert body["replay_outcome"] == "fixed"


def test_replaying_an_in_progress_run_is_refused(make_client, model_transport):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    in_progress = store.claim_run(target.id, **CLAIM)

    response = client.post(f"/api/runs/{in_progress}/replay")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "not_replayable"
    assert error["message"] == "A run still in progress can't be replayed."


def test_replaying_a_failed_or_unclear_run_is_refused_with_the_same_message(make_client, model_transport):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    target = saved_target(client.app.state.store, url=TARGET_URL)
    model_transport.verdict = "failed"
    failed = run_attack(client, target.id)
    assert failed["verdict"] == "failed"

    response = client.post(f"/api/runs/{failed['id']}/replay")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "not_replayable" and error["message"] == "Only a succeeded run can be replayed."


def test_replaying_a_run_that_never_sent_is_refused_with_the_same_message(make_client, model_transport):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    run_id = store.claim_run(target.id, **CLAIM)
    store.finish_run(run_id, failure_step="unreachable")   # verdict stays None: never reached a verdict

    response = client.post(f"/api/runs/{run_id}/replay")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "not_replayable" and error["message"] == "Only a succeeded run can be replayed."


def test_replaying_a_replay_names_its_own_source(make_client, model_transport):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    target = saved_target(client.app.state.store, url=TARGET_URL)
    model_transport.verdict = "succeeded"
    source = run_attack(client, target.id)
    model_transport.verdict = "failed"
    replay = client.post(f"/api/runs/{source['id']}/replay").json()

    response = client.post(f"/api/runs/{replay['id']}/replay")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "replay_of_replay"
    assert error["message"] == f"This run is itself a replay of run #{source['id']}."


def test_replaying_an_unknown_run_is_404(client):
    response = client.post("/api/runs/999/replay")
    assert response.status_code == 404


def test_run_in_progress_precondition_refuses_a_replay(make_client, model_transport):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    model_transport.verdict = "succeeded"
    source = run_attack(client, target.id)
    other = store.claim_run(target.id, prompt_id="spl-002", prompt_title="t2", prompt_text="<seed2>",
                            family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                            attacker_source="library:1.0.0")

    response = client.post(f"/api/runs/{source['id']}/replay")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "run_in_progress"
    assert error["message"] == "A run against this target is already in progress."
    store.finish_run(other, verdict="failed")


def test_a_replay_still_in_progress_has_no_comparison_yet(make_client, model_transport):
    """MINOR (review item 2): a replay row still in_progress - for example one entry of a batch that is still
    running, opened from another request - must never report an "inconclusive" outcome or comparison; both must
    be null until the replay actually finishes."""
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    model_transport.verdict = "succeeded"
    source = run_attack(client, target.id)
    in_progress_replay = store.claim_run(target.id, mode="replay", source_run_id=source["id"], **CLAIM)

    body = client.get(f"/api/runs/{in_progress_replay}").json()

    assert body["replay_outcome"] is None
    assert body["comparison"] is None


def test_a_replay_claim_race_returns_409_run_in_progress(make_client, model_transport, monkeypatch):
    """A RunInProgress raised by the claim itself (a genuine race between two requests on the same target) must
    be caught the same way start_run already catches it - never surface as a 500 (review item 7)."""
    from kestrel.store import RunInProgress

    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    model_transport.verdict = "succeeded"
    source = run_attack(client, target.id)

    def racing_claim_run(*args, **kwargs):
        raise RunInProgress(target.id)

    monkeypatch.setattr(store, "claim_run", racing_claim_run)

    response = client.post(f"/api/runs/{source['id']}/replay")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "run_in_progress"
    assert error["message"] == "A run against this target is already in progress."


def test_a_non_replay_run_carries_null_replay_fields(make_client, model_transport):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    target = saved_target(client.app.state.store, url=TARGET_URL)
    model_transport.verdict = "failed"
    run = run_attack(client, target.id)

    body = client.get(f"/api/runs/{run['id']}").json()

    assert body["comparison"] is None and body["replay_outcome"] is None and body["source_run_id"] is None


# ---- replay status fields depend on the target, not the run alone (research D10) ----


def test_the_run_level_ineligibility_reasons_are_pinned_word_for_word(make_client, model_transport):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)

    in_progress = store.claim_run(target.id, **CLAIM)
    body = client.get(f"/api/runs/{in_progress}").json()
    assert body["replayable"] is False
    assert body["replay_blocked_reason"] == "A run still in progress can't be replayed."

    store.finish_run(in_progress, verdict="failed")
    body = client.get(f"/api/runs/{in_progress}").json()
    assert body["replayable"] is False
    assert body["replay_blocked_reason"] == "Only a succeeded run can be replayed."


def test_replayable_becomes_false_when_the_targets_permission_lapses_then_when_terms_change(make_client,
                                                                                             model_transport):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    model_transport.verdict = "succeeded"
    source = run_attack(client, target.id)
    assert client.get(f"/api/runs/{source['id']}").json()["replayable"] is True

    with store.connect() as db:
        db.execute("UPDATE targets SET permission_confirmed_at = '' WHERE id = ?", (target.id,))
    body = client.get(f"/api/runs/{source['id']}").json()
    assert body["replayable"] is False
    assert body["replay_blocked_reason"] == "Tick the permission box and save the target before attacking it."

    with store.connect() as db:
        db.execute("UPDATE targets SET permission_confirmed_at = '2026-11-19T10:00:00Z', terms_version = 'old'"
                   " WHERE id = ?", (target.id,))
    body = client.get(f"/api/runs/{source['id']}").json()
    assert body["replayable"] is False
    assert body["replay_blocked_reason"] == "The terms of service have changed; read them and tick the box again."


def test_an_adaptive_run_whose_turns_used_lies_about_recorded_rows_is_not_replayable(make_client, model_transport):
    """Defensive (review item 3): a succeeded adaptive run whose turns_used claims messages that were never
    actually recorded - not reachable through normal operation - must not read as replayable through the real
    API, which is the only place `check_replayable`'s eligibility decision actually gates an action."""
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    run_id = store.claim_run(target.id, mode="adaptive", **CLAIM)
    store.finish_run(run_id, verdict="succeeded", turns_used=3)   # no add_turn call: zero actual run_turns rows

    body = client.get(f"/api/runs/{run_id}").json()

    assert body["replayable"] is False
    assert body["replay_blocked_reason"] == "This run has no recorded message to resend."


def test_an_adaptive_source_over_the_current_turn_limit_is_replayable_with_an_advisory(make_client, settings,
                                                                                        model_transport):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    run_id = claim_adaptive_source(store, target.id, turns=["failed"] * 8, succeeded_turn=8)

    lowered = dataclasses.replace(settings, adaptive_max_turns=6)
    lowered_client = make_client(lowered, transport=model_transport.transport, judge=real_judge(model_transport))

    body = lowered_client.get(f"/api/runs/{run_id}").json()
    assert body["replayable"] is True and body["replay_blocked_reason"] is None
    assert body["replay_advisory"] == ("This source recorded more turns than the current adaptive limit; the "
                                       "replay can end at best still vulnerable or inconclusive.")


def test_an_adaptive_source_within_the_current_turn_limit_carries_no_advisory(make_client, model_transport):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    run_id = claim_adaptive_source(store, target.id, turns=["failed", "succeeded"], succeeded_turn=2)

    body = client.get(f"/api/runs/{run_id}").json()

    assert body["replayable"] is True and body["replay_advisory"] is None


def test_an_adaptive_replays_post_body_matches_its_own_get_turn_for_turn(make_client, model_transport):
    """MAJOR (review item 1): the 201 body must show the same turns as a later GET of the same replay, not an
    empty conversation with every turn marked "not sent"."""
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    source_id = claim_adaptive_source(store, target.id, turns=["failed", "succeeded"], succeeded_turn=2)

    model_transport.verdict = "failed"
    post_body = client.post(f"/api/runs/{source_id}/replay").json()
    get_body = client.get(f"/api/runs/{post_body['id']}").json()

    assert post_body["turns"] != []
    assert post_body["turns"] == get_body["turns"]
    assert post_body["comparison"]["turns"] == get_body["comparison"]["turns"]
    assert all(turn["sent"] for turn in post_body["comparison"]["turns"])
    assert all(turn["replay_verdict"] is not None for turn in post_body["comparison"]["turns"])


def test_multi_turn_caption_present_for_a_multi_message_source_absent_for_single_message(make_client,
                                                                                          model_transport):
    client = make_client(transport=model_transport.transport, judge=real_judge(model_transport))
    store = client.app.state.store
    target = saved_target(store, url=TARGET_URL)
    source_id = claim_adaptive_source(store, target.id, turns=["failed", "succeeded"], succeeded_turn=2)

    model_transport.verdict = "failed"
    replay = client.post(f"/api/runs/{source_id}/replay").json()

    assert replay["comparison"]["multi_turn_caption"] == ("A multi-turn replay re-tests the recorded messages, "
                                                           "not an adaptive attack.")

    model_transport.verdict = "succeeded"
    single = run_attack(client, target.id)
    model_transport.verdict = "failed"
    single_replay = client.post(f"/api/runs/{single['id']}/replay").json()
    assert single_replay["comparison"]["multi_turn_caption"] is None
