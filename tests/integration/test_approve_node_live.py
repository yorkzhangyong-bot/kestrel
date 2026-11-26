"""The approve node live, end to end through the real API: the checkbox pauses before turn 2's drafted message is
sent, Approve sends and pauses again, Run to end runs unattended (never pausing again, even after a restart
partway through), Stop ends the run without sending the pending message, the target stays locked while paused, and
a decided run writes back exactly once (014/FR-015, FR-019, FR-020, FR-021, FR-022, FR-023, FR-024, FR-025,
FR-043, SC-004, SC-008, SC-015).
"""
import dataclasses

import pytest

from kestrel.attack.graph import LIVE_GRAPH
from tests.integration.test_stop_endpoint import _target
from tests.support import (SpyExperienceStore, StubEmbeddingFunction, fixture_library, model_settings,
                           real_attacker, real_judge)
from tests.unit.test_start_up_sweep_classification import _FailingPutSaver

FEATURE = "014"

DRAFTED = "<drafted message placeholder>"


def _api(settings, make_client, model_transport, *, experience=None, max_turns=6):
    capped = dataclasses.replace(model_settings(settings), adaptive_max_turns=max_turns)
    model_transport.attacker_message = DRAFTED
    model_transport.verdict = "failed"
    return make_client(capped, transport=model_transport.transport, library=fixture_library(),
                       judge=real_judge(model_transport), attacker=real_attacker(model_transport),
                       experience=experience)


def _start_paused(api, target_id: int) -> dict:
    response = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                           "mode": "adaptive", "ask_before_each_turn": True})
    assert response.status_code == 201
    return response.json()


def test_the_checkbox_pauses_before_turn_2_and_approve_sends_and_pauses_again(settings, make_client, model_transport):
    api = _api(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)

    body = _start_paused(api, target_id)
    run_id = body["id"]
    assert body["status"] == "in_progress"
    assert body["paused"] is True and body["run_state"] == "paused"
    assert body["pending_turn"]["turn"] == 2
    assert body["pending_turn"]["interrupt_id"]
    assert body["pending_turn"]["message"] == DRAFTED
    assert len(model_transport.target_requests()) == 1   # turn 1 (the library seed) sent without pausing

    # Approve: turn 2 is sent and scored, then the run pauses again before turn 3.
    response = api.post(f"/api/runs/{run_id}/decision", json={"turn": 2, "decision": "approve"})
    assert response.status_code == 200
    approved = response.json()
    assert approved["status"] == "in_progress"
    assert approved["paused"] is True and approved["run_state"] == "paused"
    assert approved["pending_turn"]["turn"] == 3
    assert len(model_transport.target_requests()) == 2   # turn 2 was sent


def test_run_to_end_runs_to_a_normal_conclusion_without_pausing(settings, make_client, model_transport):
    api = _api(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)
    body = _start_paused(api, target_id)
    run_id = body["id"]

    response = api.post(f"/api/runs/{run_id}/decision", json={"turn": 2, "decision": "run_to_end"})
    assert response.status_code == 200
    done = response.json()
    assert done["status"] == "finished"          # ran unattended to its natural stop, never pausing again
    assert done["paused"] is False
    assert done["stopping_condition"] == "turn_cap"
    assert done["turns_used"] == 6               # the full default turn budget, no turn held back
    assert len(model_transport.target_requests()) == 6   # turns 1..6 all sent


def test_a_stop_decision_ends_the_run_without_sending_the_pending_message(settings, make_client, model_transport):
    api = _api(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)
    body = _start_paused(api, target_id)
    run_id = body["id"]
    assert len(model_transport.target_requests()) == 1

    response = api.post(f"/api/runs/{run_id}/decision", json={"turn": 2, "decision": "stop"})
    assert response.status_code == 200
    stopped = response.json()
    assert stopped["status"] == "finished"
    assert stopped["stopping_condition"] == "stopped_by_user"
    assert len(model_transport.target_requests()) == 1   # the pending message was never sent
    assert len(stopped["turns"]) == 1            # no new run_turns row for the pending message


def test_the_target_stays_locked_while_paused(settings, make_client, model_transport):
    api = _api(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)
    # A prior, succeeded run of this target, so a replay has a valid source to target.
    succeeded = store.claim_run(target_id, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>",
                                family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                                attacker_source="library:1.0.0")
    store.finish_run(succeeded, verdict="succeeded", hard_evidence=True)

    run_id = _start_paused(api, target_id)["id"]

    # A new run and a replay of the other run are both refused while the target's run sits paused.
    again = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                        "mode": "adaptive"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "run_in_progress"
    replay = api.post(f"/api/runs/{succeeded}/replay")
    assert replay.status_code == 409 and replay.json()["error"]["code"] == "run_in_progress"


def test_a_decided_run_writes_back_exactly_once(settings, make_client, model_transport):
    experience = SpyExperienceStore(settings.chroma_path, embedding_function=StubEmbeddingFunction())
    api = _api(settings, make_client, model_transport, experience=experience)
    store = api.app.state.store

    target_a = _target(store, "A")
    run_a = _start_paused(api, target_a)["id"]
    api.post(f"/api/runs/{run_a}/decision", json={"turn": 2, "decision": "run_to_end"})
    assert len(experience.memory_writes) == 1

    target_b = _target(store, "B")
    run_b = _start_paused(api, target_b)["id"]
    api.post(f"/api/runs/{run_b}/decision", json={"turn": 2, "decision": "stop"})
    assert len(experience.memory_writes) == 2     # one more, never two for the same run


def test_run_to_end_survives_a_restart_without_pausing_again(settings, make_client, model_transport):
    # 014/FR-022: the flag flip is durable - cut the unattended run partway through, "restart" (a fresh app over
    # the same store), and resume: it continues without pausing, never re-reading the claim-time column.
    api = _api(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)
    body = _start_paused(api, target_id)
    run_id = body["id"]

    # Swap the saver to fail mid-way through the unattended run (after the flag flip, before the finish).
    api.app.state.live_graph = LIVE_GRAPH.copy(update={"checkpointer": _FailingPutSaver(store, 5)})
    with pytest.raises(RuntimeError):
        api.post(f"/api/runs/{run_id}/decision", json={"turn": 2, "decision": "run_to_end"})

    # A fresh app instance over the same store: the run reads as resumable, not paused, and never re-asks.
    api2 = _api(settings, make_client, model_transport)
    before = api2.get(f"/api/runs/{run_id}").json()
    assert before["run_state"] == "resumable" and before["paused"] is False

    response = api2.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 200
    done = response.json()
    assert done["status"] == "finished" and done["paused"] is False
    assert done["stopping_condition"] == "turn_cap"   # ran to its natural stop, never pausing again
