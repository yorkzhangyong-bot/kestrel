"""Nothing else changes: a single-turn run, a replay, and an experiment repetition never pause and never see the
checkbox, whatever a hostile or malformed client sends; an adaptive run with the checkbox left off never pauses,
and `run.start` omits `ask_before_each_turn` entirely (never a visible `false`) (014/FR-002, FR-031, FR-032,
SC-002, SC-003).
"""
from tests.integration.test_approve_node_live import _api
from tests.integration.test_other_run_kinds_unaffected_p1 import _run_adaptive_experiment
from tests.integration.test_stop_endpoint import _target
from tests.support import StubAttacker, StubJudge, fixture_library

FEATURE = "014"


def test_a_single_turn_run_never_pauses_and_the_checkbox_field_is_refused(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store
    target_id = _target(store)

    # A hostile client sending the checkbox for a single-turn run is refused outright (FR-002): a 422 form error.
    refused = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                          "mode": "single_turn", "ask_before_each_turn": True})
    assert refused.status_code == 422

    # A normal single-turn run never pauses.
    response = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                           "mode": "single_turn"})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "finished" and body["paused"] is False


def test_a_replay_never_pauses(settings, make_client, model_transport):
    api = _api(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)
    source = store.claim_run(target_id, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0")
    store.finish_run(source, verdict="succeeded", hard_evidence=True, stopping_condition="succeeded")
    store.add_turn(source, position=1, attacker_message="<seed>", reply_text="<reply>", judge_verdict=None)

    response = api.post(f"/api/runs/{source}/replay")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "finished" and body["paused"] is False


def test_an_adaptive_experiment_repetition_runs_the_approve_node_as_a_no_op(tmp_path, model_transport):
    # The experiment harness keeps calling the bare module-level LIVE_GRAPH, whose topology now includes the
    # approve node - but an experiment repetition never sets the flag, so every approve step is a no-op and no
    # repetition ever pauses.
    store, experiment, _ = _run_adaptive_experiment(tmp_path, model_transport)
    runs = [run for arm in experiment.arms for run in store.arm_runs(experiment.id, arm.id)]
    assert runs and all(run.status == "finished" for run in runs)


def test_an_adaptive_run_with_the_checkbox_off_never_pauses_and_omits_the_flag(settings, make_client,
                                                                               model_transport, json_log):
    api = _api(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)

    response = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                           "mode": "adaptive"})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "finished" and body["paused"] is False and body["run_state"] == "finished"

    start = [record for record in json_log() if record.get("event") == "run.start"][0]
    assert "ask_before_each_turn" not in start   # omitted entirely, never a visible `false` (FR-031)
