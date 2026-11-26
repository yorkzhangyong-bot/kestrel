"""`POST /api/runs/{id}/decision`'s validation and the execution lease (014/FR-038, FR-039, contracts/api.md): a
turn mismatch is refused with nothing sent, an invalid or missing turn/decision is a 422, two concurrent
correctly-addressed decisions resolve to exactly one success, and a refused decision writes nothing to the run's
kept log.
"""
import asyncio
import dataclasses

import httpx
import pytest

import kestrel.api.main as main
from tests.integration.test_approve_node_live import _api, _start_paused
from tests.integration.test_stop_endpoint import _claim_checkpointed, _target
from tests.support import StubAttacker, StubJudge, fixture_library, model_settings, real_attacker, real_judge

FEATURE = "014"


def test_a_decision_naming_a_turn_that_does_not_match_is_refused_with_nothing_sent(settings, make_client,
                                                                                   model_transport):
    api = _api(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)
    run_id = _start_paused(api, target_id)["id"]

    response = api.post(f"/api/runs/{run_id}/decision", json={"turn": 3, "decision": "approve"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_paused"
    assert response.json()["error"]["message"] == "This run's pending turn has already moved on."
    assert len(model_transport.target_requests()) == 1   # turn 1 only: nothing additional sent


def test_a_run_with_no_pending_decision_at_all_is_refused(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store
    target_id = _target(store)
    run_id = _claim_checkpointed(store, target_id)   # in_progress + checkpointed, but no checkpoint written yet

    response = api.post(f"/api/runs/{run_id}/decision", json={"turn": 2, "decision": "approve"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_paused"


def test_an_invalid_decision_value_or_a_missing_turn_is_a_422(settings, make_client, model_transport):
    api = _api(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)
    run_id = _start_paused(api, target_id)["id"]

    bad_value = api.post(f"/api/runs/{run_id}/decision", json={"turn": 2, "decision": "maybe"})
    assert bad_value.status_code == 422
    missing_turn = api.post(f"/api/runs/{run_id}/decision", json={"decision": "approve"})
    assert missing_turn.status_code == 422
    assert len(model_transport.target_requests()) == 1   # nothing sent by either refused request


def test_two_concurrent_decisions_exactly_one_wins_the_other_gets_run_executing(settings, make_client,
                                                                               model_transport, monkeypatch):
    api = _api(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)
    run_id = _start_paused(api, target_id)["id"]

    original = main.execute_decision

    async def slowed(*args, **kwargs):
        await asyncio.sleep(0.05)   # hold the lease while the second, concurrent request arrives
        return await original(*args, **kwargs)

    monkeypatch.setattr(main, "execute_decision", slowed)

    async def go():
        transport = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            async def decide():
                response = await client.post(f"/api/runs/{run_id}/decision",
                                             json={"turn": 2, "decision": "approve"})
                return response.status_code
            return await asyncio.gather(decide(), decide())

    codes = asyncio.run(go())
    assert sorted(codes) == [200, 409]
    assert len(model_transport.target_requests()) == 2   # turn 2 sent exactly once, never twice


def test_a_refused_decision_writes_nothing_to_the_kept_log(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store
    target_id = _target(store)
    run_id = store.claim_run(target_id, prompt_id="spl-001", prompt_title="t", prompt_text="x",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0")   # a single-turn run: never checkpointed

    response = api.post(f"/api/runs/{run_id}/decision", json={"turn": 1, "decision": "approve"})
    assert response.status_code == 409
    log = api.get(f"/api/runs/{run_id}/log").json()
    assert log["lines"] == []


def test_a_decision_reaches_the_same_preconditions_a_resume_does(settings, make_client, model_transport):
    # 014/FR-041: the decision's own preconditions (attacker configured, library available, pinned model) apply to
    # "approve"/"run_to_end" only - never "stop", which sends nothing.
    api = _api(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)
    run_id = _start_paused(api, target_id)["id"]

    # "stop" never sends and never rebuilds a client, so it succeeds even with no attacker key configured.
    bare = dataclasses.replace(model_settings(settings), attacker_api_key="")
    api2 = make_client(bare, transport=model_transport.transport, library=fixture_library(),
                       judge=real_judge(model_transport), attacker=real_attacker(model_transport))
    stopped = api2.post(f"/api/runs/{run_id}/decision", json={"turn": 2, "decision": "stop"})
    assert stopped.status_code == 200 and stopped.json()["status"] == "finished"
