"""A single-turn run, a replay, and an experiment repetition are unaffected by this feature: each still closes
exactly as `close_interrupted_runs` closed it before, never reporting `resumable: true`; an adaptive experiment
repetition's own cold arm still writes back 0 times, unwarmed by this feature's own write-back-once mechanism;
consecutive repetitions all finish and never collide on `uq_runs_active` (014/FR-001, FR-032, FR-043, FR-055,
SC-002, SC-003)."""
import asyncio

import httpx
from cryptography.fernet import Fernet

from kestrel.experiments.engine import run_experiment
from kestrel.secrets import Vault
from kestrel.settings import Settings
from kestrel.store import TargetStore
from tests.integration.test_stop_endpoint import _target
from tests.support import StubAttacker, StubJudge, fixture_library, model_settings, real_attacker, real_judge

FEATURE = "014"


def test_an_interrupted_single_turn_run_closes_exactly_as_before_never_resumable(settings, make_client):
    store = TargetStore(settings.db_path, Vault(Fernet.generate_key()))
    target_id = _target(store)
    run_id = store.claim_run(target_id, prompt_id="spl-001", prompt_title="t", prompt_text="x",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0")   # single-turn, never checkpointed - left in_progress

    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    assert store.get_run(run_id).status == "finished"   # closed by the sweep's own non-checkpointed path
    body = api.get(f"/api/runs/{run_id}").json()
    assert body["resumable"] is False and body.get("run_state") == "finished"


def test_an_interrupted_replay_closes_exactly_as_before_never_resumable(settings, make_client):
    store = TargetStore(settings.db_path, Vault(Fernet.generate_key()))
    target_id = _target(store)
    source_id = store.claim_run(target_id, prompt_id="spl-001", prompt_title="t", prompt_text="x",
                                family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                                attacker_source="library:1.0.0")
    store.finish_run(source_id, verdict="succeeded", hard_evidence=True, stopping_condition="succeeded")
    store.add_turn(source_id, position=1, attacker_message="x", reply_text="y", judge_verdict=None)
    replay_id = store.claim_run(target_id, prompt_id="spl-001", prompt_title="t", prompt_text="x",
                                family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                                attacker_source="library:1.0.0", mode="replay", source_run_id=source_id)

    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    assert store.get_run(replay_id).status == "finished"
    body = api.get(f"/api/runs/{replay_id}").json()
    assert body["resumable"] is False and body.get("run_state") == "finished"


def test_an_interrupted_experiment_repetition_closes_exactly_as_before_never_resumable(settings, make_client):
    store = TargetStore(settings.db_path, Vault(Fernet.generate_key()))
    target_id = _target(store)
    experiment = store.create_experiment(
        target_id=target_id, mode="single_turn", families=["direct_injection"], reps=1,
        seed_prompt_ids={"direct_injection": "dir-001"}, max_runs=50, token_budget_total=500_000,
        wall_clock_s=3600, arm_a={"attacker_model": "m-a", "judge_model": "j", "use_prior_experience": False,
                                  "turn_cap": 6, "token_budget": 40000, "write_back": False},
        arm_b={"attacker_model": "m-b", "judge_model": "j", "use_prior_experience": True, "turn_cap": 6,
              "token_budget": 40000, "write_back": True})
    arm = experiment.arms[0]
    run_id = store.claim_run(target_id, prompt_id="dir-001", prompt_title="t", prompt_text="x",
                             family="direct_injection", owasp_category="LLM01: Prompt Injection",
                             attacker_source="library:1.0.0")
    store.add_experiment_run(experiment_id=experiment.id, arm_id=arm.id, rep_index=1, family="direct_injection",
                             run_id=run_id)

    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    assert store.get_run(run_id).status == "finished"
    body = api.get(f"/api/runs/{run_id}").json()
    assert body["resumable"] is False and body.get("run_state") == "finished"


COLD = {"attacker_model": "deepseek/deepseek-v4.1-flash", "judge_model": "google/gemini-3.8-flash",
        "use_prior_experience": False, "turn_cap": 2, "token_budget": 40000, "write_back": False}
WARM = {"attacker_model": "deepseek/deepseek-v4.1-flash", "judge_model": "google/gemini-3.8-flash",
        "use_prior_experience": True, "turn_cap": 2, "token_budget": 40000, "write_back": True}


class _Experience:
    def __init__(self):
        self.writes = 0

    def write_memory(self, **kw):
        self.writes += 1

    def write_pattern(self, **kw):
        from kestrel.experience.store import PatternWrite
        self.writes += 1
        return PatternWrite("added", "pattern:run:0", 1, None)

    def retrieve_memory(self, **kw):
        return []

    def retrieve_patterns(self, **kw):
        return []

    def count(self, type=None, *, family=None, target_id=None):
        return 0

    def query_patterns(self, **kw):
        return []


def _run_adaptive_experiment(tmp_path, model_transport, *, reps=1):
    store = TargetStore(tmp_path / "k.db", Vault(Fernet.generate_key()))
    target = store.create_target(name="A", url="http://t/chat", method="POST", headers=[],
                                 body_template='{"message":"{{prompt}}"}', response_path="$.reply",
                                 terms_version="6")
    experiment = store.create_experiment(
        target_id=target.id, mode="adaptive", families=["system_prompt_leak"], reps=reps,
        seed_prompt_ids={"system_prompt_leak": "spl-001"}, max_runs=50, token_budget_total=500_000,
        wall_clock_s=3600, arm_a=COLD, arm_b=WARM)
    experience = _Experience()
    settings = Settings(mode="local", db_path=tmp_path / "k.db", key_file=tmp_path / "key", secret_key=None,
                       judge_api_key="k", attacker_api_key="k")
    asyncio.run(run_experiment(store, experiment_id=experiment.id, settings=settings, library=fixture_library(),
                               experience=experience, transport=model_transport.transport))
    return store, store.get_experiment(experiment.id), experience


def test_an_adaptive_experiment_repetitions_cold_arm_still_writes_back_zero_times(tmp_path, model_transport):
    store, experiment, experience = _run_adaptive_experiment(tmp_path, model_transport)
    arms = {a.label: a for a in experiment.arms}
    cold_runs = store.arm_runs(experiment.id, arms["A"].id)
    warm_runs = store.arm_runs(experiment.id, arms["B"].id)
    assert cold_runs and warm_runs
    assert all(run.memory_written is None for run in cold_runs)
    assert all(run.memory_written is True for run in warm_runs)


def test_consecutive_experiment_repetitions_all_finish_and_next_claim_succeeds(tmp_path, model_transport):
    store, experiment, _ = _run_adaptive_experiment(tmp_path, model_transport, reps=3)
    runs = [r for arm in experiment.arms for r in store.arm_runs(experiment.id, arm.id)]
    assert len(runs) == 3 * 2   # 3 repetitions x 2 arms
    assert all(r.status == "finished" for r in runs)   # never left in_progress - the next claim never refused
