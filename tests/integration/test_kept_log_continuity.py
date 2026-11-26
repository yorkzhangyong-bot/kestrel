"""The kept log survives across a run's own resumed segments: no sequence-number collision, correct order, and
`run.interrupted` lands in the *kept* log too, not only the stream (014/FR-017, SC-006, SC-017, research D20).

Every segment (the original start and each resume) is driven through the real API, never a direct graph.ainvoke
call bypassing it - a kept log line only exists inside an open `events.run_scope`/`reopened_run_scope`, which only
the real endpoints open. `store.list_log_lines` is the source of each line's own `seq` (the API's own `/log`
response carries the raw JSON record, never that internal ordering column, by design - FR-009's allow-list)."""
import pytest

from kestrel.attack.graph import LIVE_GRAPH
from tests.integration.test_stop_endpoint import _target
from tests.support import fixture_library, model_settings, real_attacker, real_judge
from tests.unit.test_start_up_sweep_classification import _FailingPutSaver

FEATURE = "014"


def _swap_saver(api, fail_at: int):
    """A fresh fault-injecting saver on the app's own live graph, counting puts from zero for whatever happens
    next (this segment's own node sequence, starting from wherever the checkpoint left off)."""
    saver = _FailingPutSaver(api.app.state.store, fail_at)
    api.app.state.live_graph = LIVE_GRAPH.copy(update={"checkpointer": saver})


def _restore_saver(api):
    from kestrel.checkpointing import KestrelCheckpointSaver
    api.app.state.live_graph = LIVE_GRAPH.copy(update={"checkpointer": KestrelCheckpointSaver(api.app.state.store)})


def test_a_run_resumed_twice_has_no_seq_collision_and_run_interrupted_is_kept(settings, make_client, model_transport):
    api = make_client(model_settings(settings), transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), attacker=real_attacker(model_transport))
    store = api.app.state.store
    target = _target(store)

    # Segment 1 (the original start): cut mid-turn-1, before any outcome.
    _swap_saver(api, 4)
    with pytest.raises(RuntimeError):
        api.post("/api/runs", json={"target_id": target, "family": "system_prompt_leak", "mode": "adaptive",
                                    "adaptive_max_turns": 3})
    run_id = store.list_runs(target)[0].id

    lines_1 = store.list_log_lines(run_id)
    assert lines_1 != []
    seqs_1 = [line.seq for line in lines_1]
    assert seqs_1 == sorted(seqs_1) and len(set(seqs_1)) == len(seqs_1)
    assert len([line for line in lines_1 if line.event == "run.interrupted"]) == 1   # kept, not only on the stream

    # Segment 2 (the first resume): cut again, partway through.
    _swap_saver(api, 2)
    with pytest.raises(RuntimeError):
        api.post(f"/api/runs/{run_id}/resume")

    lines_2 = store.list_log_lines(run_id)
    seqs_2 = [line.seq for line in lines_2]
    assert seqs_2 == sorted(seqs_2) and len(set(seqs_2)) == len(seqs_2)
    assert seqs_2[: len(seqs_1)] == seqs_1   # segment 1's own lines are an unbroken prefix, never renumbered
    assert len(lines_2) > len(lines_1)
    interrupted_2 = [line for line in lines_2 if line.event == "run.interrupted"]
    assert len(interrupted_2) == 2   # one per crashed segment so far, each kept - never only on the stream

    # The API's own /log response matches the store's kept lines exactly (same count, same events, in order).
    api_lines_2 = api.get(f"/api/runs/{run_id}/log").json()["lines"]
    assert [line["event"] for line in api_lines_2] == [line.event for line in lines_2]

    # Segment 3 (the second resume): let it run to a natural finish.
    _restore_saver(api)
    response = api.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 200 and response.json()["status"] == "finished"

    lines_3 = store.list_log_lines(run_id)
    seqs_3 = [line.seq for line in lines_3]
    assert seqs_3 == sorted(seqs_3) and len(set(seqs_3)) == len(seqs_3)
    assert seqs_3[: len(seqs_2)] == seqs_2
    assert len(lines_3) > len(lines_2)
    assert lines_3[-1].event == "run.end"   # the whole run's own, single, final line
