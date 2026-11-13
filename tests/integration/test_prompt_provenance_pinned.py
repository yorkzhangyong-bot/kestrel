"""The recorded provenance and the log lines name the version actually sent — a pinned arm's, not the active one —
and judge provenance exists only where a judge request was made (010/FR-007, 010/SC-001). A temporary registry
holds a version 2 of the judge and of one attacker prompt beside version 1; real clients, offline transport."""
import pytest

from kestrel import prompt_registry as pr
from kestrel.judge.client import JudgeClient
from tests.support import (MODEL_BASE_URL, await_experiment, fixture_library, model_settings, real_attacker,
                           real_judge, saved_target)

FEATURE = "010"

ATTACKER_ID = "attacker:system_prompt_leak"
ARM = {"attacker_model": "deepseek/deepseek-v4.1-flash", "judge_model": "google/gemini-3.8-flash",
       "turn_cap": 2, "token_budget": 40000, "write_back": True}
CANARY = "KESTREL-CANARY-PLACEHOLDER-55"


@pytest.fixture
def two_versions(tmp_path, monkeypatch):
    """A registry where `judge` and `attacker:system_prompt_leak` have an active version 2 beside version 1."""
    directory = tmp_path / "prompts"
    directory.mkdir()
    for path in pr.PROMPTS_DIR.glob("*.md"):
        (directory / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    for prompt_id in ("judge", ATTACKER_ID):
        text = pr.text_for(prompt_id, "1") + "\n\nVersion two of this prompt."
        pr.prompt_path(prompt_id, "2", directory).write_text(pr.format_prompt_file(prompt_id, "2", text),
                                                             encoding="utf-8", newline="\n")
    monkeypatch.setattr(pr, "PROMPTS_DIR", directory)
    assert pr.active_version("judge") == "2" and pr.active_version(ATTACKER_ID) == "2"


def experiment(make_client, settings, model_transport, arm_b_pin):
    api = make_client(model_settings(settings), transport=model_transport.transport, library=fixture_library())
    target = saved_target(api.app.state.store)
    request = {"target_id": target.id, "mode": "adaptive", "families": ["system_prompt_leak"], "reps": 1,
               "arm_a": {**ARM, "use_prior_experience": False},
               "arm_b": {**ARM, "use_prior_experience": False, **arm_b_pin}}
    response = api.post("/api/experiments", json=request)
    assert response.status_code == 201, response.text
    experiment_id = response.json()["id"]
    assert await_experiment(api, experiment_id)["status"] == "finished"
    store = api.app.state.store
    return store, {arm.label: store.arm_runs(experiment_id, arm.id)[0]
                   for arm in store.get_experiment(experiment_id).arms}


def lines_of(json_log, run_id, event, **match):
    return [r for r in json_log() if r.get("run_id") == run_id and r["event"] == event
            and all(r.get(k) == v for k, v in match.items())]


def test_a_pinned_judge_arm_records_and_logs_the_pinned_version(two_versions, make_client, settings,
                                                               model_transport, json_log):  # FR-007, SC-001
    store, runs = experiment(make_client, settings, model_transport,
                             {"prompt_arm_target": "judge", "prompt_arm_version": "1"})
    for label, version in (("A", "2"), ("B", "1")):
        run = store.get_run(runs[label].id)
        assert (run.judge_prompt_id, run.judge_prompt_version) == ("judge", version), label
        judged = [t for t in store.list_turns(run.id) if t.judge_prompt_id]
        assert judged and all(t.judge_prompt_version == version for t in judged), label
        reference = f"judge@{version}"
        assert lines_of(json_log, run.id, "run.start")[0]["judge_prompt"] == reference
        assert all(t["judge_prompt"] == reference for t in lines_of(json_log, run.id, "turn"))
        judge_lines = lines_of(json_log, run.id, "model.request", kind="judge")
        assert judge_lines and all(r["prompt"] == reference for r in judge_lines)


def test_a_pinned_attacker_arm_records_and_logs_the_pinned_version(two_versions, make_client, settings,
                                                                  model_transport, json_log):  # FR-007, SC-001
    store, runs = experiment(make_client, settings, model_transport,
                             {"prompt_arm_target": ATTACKER_ID, "prompt_arm_version": "1"})
    for label, version in (("A", "2"), ("B", "1")):
        run_id = runs[label].id
        generated = [t for t in store.list_turns(run_id) if t.attacker_prompt_id]
        assert generated and all((t.attacker_prompt_id, t.attacker_prompt_version) == (ATTACKER_ID, version)
                                 for t in generated), label
        reference = f"{ATTACKER_ID}@{version}"
        assert lines_of(json_log, run_id, "run.start")[0]["attacker_prompt"] == reference
        attacker_lines = lines_of(json_log, run_id, "model.request", kind="attacker")
        assert attacker_lines and all(r["prompt"] == reference for r in attacker_lines)
        assert all(t["attacker_prompt"] == reference for t in lines_of(json_log, run_id, "turn") if t["turn"] >= 2)


def single_turn(make_client, settings, model_transport, *, judge=None, canaries=None, mode="single_turn"):
    api = make_client(settings, transport=model_transport.transport, library=fixture_library(),
                      judge=judge or real_judge(model_transport), attacker=real_attacker(model_transport))
    target = saved_target(api.app.state.store, canaries=canaries)
    response = api.post("/api/runs", json={"target_id": target.id, "family": "system_prompt_leak", "mode": mode})
    assert response.status_code == 201, response.text
    return api.app.state.store, response.json()["id"]


def test_a_single_turn_verdict_records_the_reference_its_judge_line_names(two_versions, make_client, settings,
                                                                         model_transport, json_log):  # FR-007
    store, run_id = single_turn(make_client, settings, model_transport)
    judge_line = lines_of(json_log, run_id, "model.request", kind="judge")[0]
    run = store.get_run(run_id)
    assert judge_line["prompt"] == f"{run.judge_prompt_id}@{run.judge_prompt_version}" == "judge@2"


def test_an_adaptive_run_without_a_judge_records_and_logs_no_judge_reference(make_client, settings, model_transport,
                                                                             json_log):  # FR-007
    unconfigured = JudgeClient(model="google/gemini-3.8-flash", api_key=None, base_url=MODEL_BASE_URL,
                               transport=model_transport.transport)
    store, run_id = single_turn(make_client, settings, model_transport, judge=unconfigured, mode="adaptive")
    run = store.get_run(run_id)
    assert (run.judge_prompt_id, run.judge_prompt_version) == (None, None)
    assert all((t.judge_prompt_id, t.judge_prompt_version) == (None, None) for t in store.list_turns(run_id))
    assert "judge_prompt" not in lines_of(json_log, run_id, "run.start")[0]


def test_a_canary_decided_turn_records_null_judge_provenance_and_a_null_line_reference(make_client, settings,
                                                                                       model_transport, json_log):
    # FR-007
    model_transport.target_reply = f"leaked {CANARY}"
    store, run_id = single_turn(make_client, settings, model_transport, canaries=[CANARY], mode="adaptive")
    turn = store.list_turns(run_id)[0]
    assert (turn.judge_prompt_id, turn.judge_prompt_version) == (None, None)
    line = lines_of(json_log, run_id, "turn")[0]
    assert line["canary_hit"] is True and "judge_prompt" in line and line["judge_prompt"] is None
