"""Experiment persistence on TargetStore (feature 007). Traces 007/FR-003, 007/FR-004, 007/FR-016."""
import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import ExperimentInProgress, TargetStore

FEATURE = "007"

ARM_A = {"attacker_model": "m-a", "judge_model": "j", "use_prior_experience": False,
         "turn_cap": 6, "token_budget": 40000, "write_back": False}
ARM_B = {"attacker_model": "m-b", "judge_model": "j", "use_prior_experience": True,
         "turn_cap": 6, "token_budget": 40000, "write_back": True}


@pytest.fixture
def store(tmp_path):
    return TargetStore(tmp_path / "k.db", Vault(Fernet.generate_key()))


@pytest.fixture
def target(store):
    return store.create_target(name="A", url="http://t/chat", method="POST", headers=[],
                               body_template="{}", response_path="$.reply", terms_version="6")


def _create(store, target):
    return store.create_experiment(
        target_id=target.id, mode="adaptive",
        families=["direct_injection", "system_prompt_leak"], reps=3,
        seed_prompt_ids={"direct_injection": "dir-001", "system_prompt_leak": "spl-001"},
        max_runs=50, token_budget_total=500_000, wall_clock_s=3600, arm_a=ARM_A, arm_b=ARM_B)


def test_create_experiment_with_two_arms(store, target):
    exp = _create(store, target)
    assert exp.status == "running" and exp.reps == 3
    assert exp.families == ("direct_injection", "system_prompt_leak")
    assert exp.seed_prompt_ids["direct_injection"] == "dir-001"
    arms = {a.label: a for a in exp.arms}
    assert set(arms) == {"A", "B"}
    assert arms["A"].use_prior_experience is False and arms["A"].write_back is False
    assert arms["B"].use_prior_experience is True and arms["B"].write_back is True
    assert store.get_experiment(exp.id).arms[0].label == "A"   # round-trips, sorted


def test_one_running_experiment_per_target(store, target):
    _create(store, target)
    with pytest.raises(ExperimentInProgress):
        _create(store, target)
    exp = store.list_experiments(target.id)[0]
    store.set_experiment_status(exp.id, status="finished", stopped_reason="completed", finished=True)
    _create(store, target)   # a second is allowed once the first is done


def test_add_experiment_run_links_a_run(store, target):
    exp = _create(store, target)
    arm_a = next(a for a in exp.arms if a.label == "A")
    run_id = store.claim_run(target.id, prompt_id="dir-001", prompt_title="t", prompt_text="<p>",
                             family="direct_injection", owasp_category="LLM01: Prompt Injection",
                             attacker_source="library:1")
    store.finish_run(run_id, verdict="failed", tokens_used=120)
    store.add_experiment_run(experiment_id=exp.id, arm_id=arm_a.id, rep_index=0,
                             family="direct_injection", run_id=run_id)
    runs = store.arm_runs(exp.id, arm_a.id)
    assert len(runs) == 1 and runs[0].tokens_used == 120
    assert store.experiment_progress(exp.id)["completed"] == 1


def test_run_recorded_even_when_send_failed(store, target):
    exp = _create(store, target)
    arm_a = next(a for a in exp.arms if a.label == "A")
    store.add_experiment_run(experiment_id=exp.id, arm_id=arm_a.id, rep_index=0,
                             family="direct_injection", run_id=None, send_ok=False)
    links = store.experiment_run_links(exp.id)
    assert len(links) == 1 and links[0].run_id is None and links[0].send_ok is False


def test_set_arm_order_and_status(store, target):
    exp = _create(store, target)
    for order, arm in enumerate(sorted(exp.arms, key=lambda a: a.label), start=1):
        store.set_arm_order(arm.id, order)
    store.set_experiment_status(exp.id, status="stopped", stopped_reason="max_runs", finished=True)
    got = store.get_experiment(exp.id)
    assert got.status == "stopped" and got.stopped_reason == "max_runs" and got.finished_at is not None
    assert {a.run_order for a in got.arms} == {1, 2}
