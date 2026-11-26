"""No checkpoint row survives any finishing path, and deleting a target removes every checkpoint thread for its
own runs (014/FR-006, FR-045, SC-019)."""
import asyncio
import dataclasses

import pytest

from kestrel.attack.graph import LIVE_GRAPH, _initial_state
from tests.integration.test_stop_endpoint import _claim_checkpointed, _target
from tests.support import StubAttacker, StubJudge, fixture_library, model_settings, real_attacker, real_judge
from tests.unit.test_adaptive_graph_state import make_deps, numbered_sender
from tests.unit.test_start_up_sweep_classification import _FailingPutSaver

FEATURE = "014"


def _checkpoint_count(store, run_id) -> int:
    with store.connect() as db:
        return db.execute("SELECT COUNT(*) AS n FROM checkpoints WHERE thread_id = ?",
                          (str(run_id),)).fetchone()["n"]


def test_a_clean_finish_leaves_no_checkpoint(settings, make_client, model_transport):
    api = make_client(model_settings(settings), transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), attacker=real_attacker(model_transport))
    store = api.app.state.store
    target_id = _target(store)
    response = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                           "mode": "adaptive"})
    assert response.status_code == 201
    run_id = response.json()["id"]
    assert _checkpoint_count(store, run_id) == 0


def test_a_stop_leaves_no_checkpoint(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store
    target_id = _target(store)
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
    assert _checkpoint_count(store, run_id) > 0
    response = api.post(f"/api/runs/{run_id}/stop")
    assert response.status_code == 200
    assert _checkpoint_count(store, run_id) == 0


def test_the_sweeps_own_close_and_reconcile_paths_leave_no_checkpoint(settings, make_client):
    store_settings = settings
    from kestrel.store import TargetStore
    from kestrel.secrets import Vault
    from cryptography.fernet import Fernet
    store = TargetStore(store_settings.db_path, Vault(Fernet.generate_key()))
    target_id = _target(store)

    # A reached-its-own-end row: the sweep reconciles it.
    run_a = _claim_checkpointed(store, target_id)
    saver = _FailingPutSaver(store, 99)   # never fails: a real, uninterrupted finish
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = dataclasses.replace(
        make_deps(store=store, sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                 attacker=StubAttacker(), max_turns=1),
        run_id=run_a)
    asyncio.run(copied.ainvoke(_initial_state(), {"configurable": {"thread_id": str(run_a)}}, context=deps,
                              durability="sync"))
    assert _checkpoint_count(store, run_a) > 0

    # A no-checkpoint row: the sweep closes it, trivially (nothing to delete, but it must not error either).
    target_id_2 = _target(store, "B")
    run_b = _claim_checkpointed(store, target_id_2)

    api = make_client(store_settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    assert _checkpoint_count(store, run_a) == 0
    assert _checkpoint_count(store, run_b) == 0
    assert store.get_run(run_a).status == "finished" and store.get_run(run_b).status == "finished"


def test_deleting_a_target_removes_every_checkpoint_thread_for_its_own_runs(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store
    target_id = _target(store)
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
    assert _checkpoint_count(store, run_id) > 0

    response = api.delete(f"/api/targets/{target_id}")
    assert response.status_code == 204
    assert _checkpoint_count(store, run_id) == 0
