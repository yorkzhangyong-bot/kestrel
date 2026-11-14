"""An experiment's lines: experiment.start, every record of its runs stamped with the experiment id and arm — the
write-back line included — a cap stop, and experiment.end (010/FR-005, FR-007, FR-016, SC-008). The engine's own
factories build real model clients over the offline transport; placeholders only."""
from tests.support import await_experiment, fixture_library, model_settings, saved_target

FEATURE = "010"

ARM = {"attacker_model": "deepseek/deepseek-v4.1-flash", "judge_model": "google/gemini-3.8-flash",
       "turn_cap": 2, "token_budget": 40000, "write_back": True}
ARM_A = {**ARM, "use_prior_experience": False}
ARM_B = {**ARM, "use_prior_experience": True, "prompt_arm_target": "judge", "prompt_arm_version": "1"}


def start_experiment(make_client, settings, model_transport, **body):
    api = make_client(model_settings(settings), transport=model_transport.transport, library=fixture_library())
    target = saved_target(api.app.state.store)
    request = {"target_id": target.id, "mode": "adaptive", "families": ["system_prompt_leak"], "reps": 1,
               "arm_a": ARM_A, "arm_b": ARM_B, **body}
    response = api.post("/api/experiments", json=request)
    assert response.status_code == 201, response.text
    experiment_id = response.json()["id"]
    return api, experiment_id, await_experiment(api, experiment_id)


def test_every_record_of_an_experiments_runs_carries_its_experiment_and_arm(make_client, settings, model_transport,
                                                                            json_log):  # FR-005, SC-008
    api, experiment_id, status = start_experiment(make_client, settings, model_transport)
    assert status["status"] == "finished"
    runs = {run.id: arm.label for arm in api.app.state.store.get_experiment(experiment_id).arms
            for run in api.app.state.store.arm_runs(experiment_id, arm.id)}
    assert sorted(runs.values()) == ["A", "B"]
    for run_id, label in runs.items():
        lines = [r for r in json_log() if r.get("run_id") == run_id]
        assert lines and all(r["experiment_id"] == experiment_id and r["arm"] == label for r in lines)
        events = [r["event"] for r in lines]
        assert events[0] == "run.start" and events[-2:] == ["memory.writeback", "run.end"]


def test_experiment_start_and_end_frame_the_runs(make_client, settings, model_transport, json_log):  # FR-016
    _api, experiment_id, _status = start_experiment(make_client, settings, model_transport)
    start = json_log.of("experiment.start")[0]
    assert start["experiment_id"] == experiment_id and start["mode"] == "adaptive" and start["reps"] == 1
    assert start["families"] == ["system_prompt_leak"] and start["max_runs"] >= 2
    assert [arm["label"] for arm in start["arms"]] == ["A", "B"]
    assert start["arms"][0]["prompt"] is None and start["arms"][1]["prompt"] == "judge@1"
    assert "arm" not in start and "run_id" not in start
    end = json_log.of("experiment.end")[0]
    assert end["experiment_id"] == experiment_id and end["status"] == "finished"
    assert end["stopped_reason"] == "completed" and end["completed_runs"] == 2 and end["tokens_used"] > 0
    assert end["duration_ms"] >= 0 and "error" not in end
    events = json_log.events()
    assert events.index("experiment.start") < events.index("run.start")
    assert events.index("experiment.end") > max(i for i, event in enumerate(events) if event == "run.end")


def test_the_pinned_arms_judge_lines_name_the_pinned_version(make_client, settings, model_transport, json_log):
    # FR-007
    api, experiment_id, _status = start_experiment(make_client, settings, model_transport)
    arm_b = next(arm for arm in api.app.state.store.get_experiment(experiment_id).arms if arm.label == "B")
    run_b = api.app.state.store.arm_runs(experiment_id, arm_b.id)[0]
    judge_lines = [r for r in json_log.of("model.request") if r.get("run_id") == run_b.id and r["kind"] == "judge"]
    assert judge_lines and all(r["prompt"] == "judge@1" for r in judge_lines)


def test_a_cap_stop_is_logged_with_the_cap_and_what_was_done(make_client, settings, model_transport, json_log):
    # FR-016
    _api, experiment_id, status = start_experiment(make_client, settings, model_transport, caps={"max_runs": 1})
    assert status["status"] == "stopped"
    cap = json_log.of("experiment.cap")[0]
    assert cap["experiment_id"] == experiment_id and cap["cap"] == "max_runs" and cap["level"] == "WARNING"
    assert cap["completed_runs"] == 1 and cap["tokens_used"] > 0 and cap["elapsed_s"] >= 0
    end = json_log.of("experiment.end")[0]
    assert end["status"] == "stopped" and end["stopped_reason"] == "max_runs" and end["completed_runs"] == 1
