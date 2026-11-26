"""`GET /api/runs/{id}`'s own `resumable`/`paused`/`run_state` fields and `POST /api/runs/{id}/resume`'s
documented preconditions and outcomes, and the target lock a resumable run holds against a new run or a replay
(014/FR-041, FR-054, FR-015, SC-008, contracts/api.md)."""
import asyncio
import dataclasses

import pytest

from kestrel.api.main import load_terms
from kestrel.attack.graph import LIVE_GRAPH
from tests.integration.test_stop_endpoint import _claim_checkpointed, _target
from tests.support import StubAttacker, StubJudge, fixture_library, model_settings, real_attacker, real_judge
from tests.unit.test_start_up_sweep_classification import _FailingPutSaver

FEATURE = "014"

CURRENT_TERMS = load_terms().version


def _cut_resumable_run(api, name="A"):
    store = api.app.state.store
    target_id = _target(store, name)
    run_id = _claim_checkpointed(store, target_id)
    saver = _FailingPutSaver(store, 4)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    config = {"configurable": {"thread_id": str(run_id)}}
    from kestrel.attack.graph import _initial_state
    from tests.unit.test_adaptive_graph_state import make_deps, numbered_sender
    deps = dataclasses.replace(
        make_deps(store=store, sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                 attacker=StubAttacker(), max_turns=2),
        run_id=run_id)
    with pytest.raises(RuntimeError):
        asyncio.run(copied.ainvoke(_initial_state(), config, context=deps, durability="sync"))
    return run_id, target_id


def test_a_resumable_run_reports_itself_correctly_and_resumes_to_completion(settings, make_client, model_transport):
    api = make_client(model_settings(settings), transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), attacker=real_attacker(model_transport))
    run_id, target_id = _cut_resumable_run(api)

    before = api.get(f"/api/runs/{run_id}").json()
    assert before["resumable"] is True and before["paused"] is False and before["run_state"] == "resumable"

    response = api.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 200 and response.json()["status"] == "finished"

    # The target's lock is released: a replay or a new run now succeeds.
    r2 = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak", "mode": "single_turn"})
    assert r2.status_code == 201


def test_resume_refuses_with_the_documented_precondition_errors(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store

    # Already finished.
    target_a = _target(store, "A")
    run_a = _claim_checkpointed(store, target_a)
    store.finish_run(run_a, verdict="failed", stopping_condition="turn_cap")
    r = api.post(f"/api/runs/{run_a}/resume")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_resumable"

    # Non-adaptive (never checkpointed).
    target_b = _target(store, "B")
    run_b = store.claim_run(target_b, prompt_id="spl-001", prompt_title="t", prompt_text="x",
                            family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                            attacker_source="library:1.0.0")
    r = api.post(f"/api/runs/{run_b}/resume")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_resumable"

    # Currently leased.
    run_id, _ = _cut_resumable_run(api, "C")
    api.app.state.leases.add(run_id)
    r = api.post(f"/api/runs/{run_id}/resume")
    assert r.status_code == 409 and r.json()["error"]["code"] == "run_executing"
    api.app.state.leases.discard(run_id)


def test_resume_refuses_terms_outdated_before_anything_is_sent(settings, make_client, model_transport):
    # permission_confirmed_at is NOT NULL once a target is created at all (create_target always sets it), so
    # "permission_missing" is not independently constructible here - the original start's own existing tests
    # already cover that precondition's refusal path.
    api = make_client(model_settings(settings), transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), attacker=real_attacker(model_transport))
    run_id, target_id = _cut_resumable_run(api)
    store = api.app.state.store

    with store.connect() as db:
        db.execute("UPDATE targets SET terms_version = 'stale' WHERE id = ?", (target_id,))
    r = api.post(f"/api/runs/{run_id}/resume")
    assert r.status_code == 409 and r.json()["error"]["code"] == "terms_outdated"
    assert model_transport.requests == []


def test_resume_refuses_attacker_unavailable_before_anything_is_sent(settings, make_client, model_transport):
    no_key_settings = dataclasses.replace(model_settings(settings), attacker_api_key="")
    api = make_client(no_key_settings, transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), attacker=real_attacker(model_transport))
    run_id, _ = _cut_resumable_run(api)
    r = api.post(f"/api/runs/{run_id}/resume")
    assert r.status_code == 409 and r.json()["error"]["code"] == "attacker_unavailable"
    assert model_transport.requests == []


def test_starting_a_new_run_against_a_resumable_targets_own_run_refuses_run_in_progress(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    run_id, target_id = _cut_resumable_run(api)
    r = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak", "mode": "single_turn"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "run_in_progress"


def test_a_leased_run_reads_running_and_offers_no_control(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    run_id, _ = _cut_resumable_run(api)
    api.app.state.leases.add(run_id)   # simulates "currently executing" for classify_run's own read side
    try:
        body = api.get(f"/api/runs/{run_id}").json()
        assert body["run_state"] == "running"
        assert body["resumable"] is False and body["paused"] is False
    finally:
        api.app.state.leases.discard(run_id)
