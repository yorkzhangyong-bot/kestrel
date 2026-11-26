"""A paused run survives a restart exactly like a crashed one (014/FR-014, SC-004, User Story 3): the second app
instance over the same store reports the identical pending turn and decides it identically; and a decision cut off
before its own commit classifies as resumable, not paused - the already-applied decision is never re-shown, and
resuming continues without re-sending anything. Proof of composition: no production code beyond part 1 and
T044/T050.
"""
import pytest

from kestrel.attack.graph import LIVE_GRAPH
from tests.integration.test_approve_node_live import _api, _start_paused
from tests.integration.test_stop_endpoint import _target
from tests.unit.test_start_up_sweep_classification import _FailingPutSaver

FEATURE = "014"


def test_a_paused_run_survives_a_restart_and_decides_identically(settings, make_client, model_transport):
    api1 = _api(settings, make_client, model_transport)
    store = api1.app.state.store
    target_id = _target(store)
    body = _start_paused(api1, target_id)
    run_id = body["id"]

    # A fresh app instance over the same store: the identical pending turn, never silently closed or resolved.
    api2 = _api(settings, make_client, model_transport)
    before = api2.get(f"/api/runs/{run_id}").json()
    assert before["paused"] is True and before["run_state"] == "paused"
    assert before["pending_turn"] == body["pending_turn"]

    response = api2.post(f"/api/runs/{run_id}/decision", json={"turn": 2, "decision": "approve"})
    assert response.status_code == 200
    approved = response.json()
    assert approved["paused"] is True and approved["pending_turn"]["turn"] == 3   # decided identically, no gap


def test_a_decision_cut_off_before_its_commit_classifies_resumable_not_paused(settings, make_client, model_transport):
    # US3 scenario 3: a decision applied (its message already sent) but cut before the next pause committed. The
    # run reads resumable, not paused - the already-applied decision is not re-shown - and resuming never re-sends.
    api1 = _api(settings, make_client, model_transport)
    store = api1.app.state.store
    target_id = _target(store)
    run_id = _start_paused(api1, target_id)["id"]
    assert len(model_transport.target_requests()) == 1   # turn 1 only

    # Fail right after the approved turn's send committed (its own write landed), before evidence's commit.
    api1.app.state.live_graph = LIVE_GRAPH.copy(update={"checkpointer": _FailingPutSaver(store, 4)})
    with pytest.raises(RuntimeError):
        api1.post(f"/api/runs/{run_id}/decision", json={"turn": 2, "decision": "approve"})
    assert len(model_transport.target_requests()) == 2   # turn 2 was already sent, for real

    api2 = _api(settings, make_client, model_transport)
    before = api2.get(f"/api/runs/{run_id}").json()
    assert before["run_state"] == "resumable" and before["paused"] is False
    assert before["pending_turn"] is None               # the decision is not re-shown

    response = api2.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 200
    resumed = response.json()
    # Continues correctly: no re-send of turn 2, and (the flag is still on) pauses again before turn 3.
    assert len(model_transport.target_requests()) == 2
    assert resumed["paused"] is True and resumed["pending_turn"]["turn"] == 3
