"""A target's OWASP report excludes a paused run, a resumable run, and a currently-leased/executing run - the same
way it already excludes a replay (014/FR-050, research D25)."""
import asyncio
import dataclasses

import pytest

from kestrel.attack.graph import LIVE_GRAPH, _initial_state
from tests.integration.test_stop_endpoint import _claim_checkpointed, _target
from tests.support import StubAttacker, StubJudge, fixture_library
from tests.unit.test_adaptive_graph_state import make_deps, numbered_sender
from tests.unit.test_start_up_sweep_classification import _FailingPutSaver

FEATURE = "014"


def _resumable_run(store, target_id):
    run_id = _claim_checkpointed(store, target_id)
    saver = _FailingPutSaver(store, 3)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = dataclasses.replace(
        make_deps(store=store, sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                 attacker=StubAttacker(), max_turns=2),
        run_id=run_id)
    config = {"configurable": {"thread_id": str(run_id)}}
    with pytest.raises(RuntimeError):
        asyncio.run(copied.ainvoke(_initial_state(), config, context=deps, durability="sync"))
    return run_id


def test_a_resumable_run_is_excluded_from_the_report(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store
    target_id = _target(store)
    run_id = _resumable_run(store, target_id)

    response = api.get(f"/api/targets/{target_id}/report")
    assert response.status_code == 200
    assert str(run_id) not in response.text


def test_a_currently_leased_run_is_excluded_from_the_report(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store
    target_id = _target(store)
    run_id = _resumable_run(store, target_id)
    api.app.state.leases.add(run_id)
    try:
        response = api.get(f"/api/targets/{target_id}/report")
        assert response.status_code == 200
        assert str(run_id) not in response.text
    finally:
        api.app.state.leases.discard(run_id)


def test_generating_the_report_does_not_change_the_runs_own_status(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store
    target_id = _target(store)
    run_id = _resumable_run(store, target_id)
    api.get(f"/api/targets/{target_id}/report")
    assert store.get_run(run_id).status == "in_progress"
