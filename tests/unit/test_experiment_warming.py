"""A cold arm is not warmed by the other: write-back is skipped and the order is recorded (feature 007).

Traces 007/FR-005, 007/SC-005. Stub judge + experience, MockTransport - no network, no attack text.
"""
import asyncio

import httpx
from cryptography.fernet import Fernet

from kestrel.experiments.engine import run_experiment
from kestrel.secrets import Vault
from kestrel.settings import Settings
from kestrel.store import TargetStore
from tests.support import StubJudge, fixture_library

FEATURE = "007"

COLD = {"attacker_model": "m-a", "judge_model": "j", "use_prior_experience": False,
        "turn_cap": 6, "token_budget": 40000, "write_back": False}   # cold arm: no write-back
WARM = {"attacker_model": "m-b", "judge_model": "j", "use_prior_experience": True,
        "turn_cap": 6, "token_budget": 40000, "write_back": True}    # warm arm: writes back


class _Experience:
    def __init__(self):
        self.writes = 0

    def write_memory(self, **kw):
        self.writes += 1

    def write_pattern(self, **kw):
        self.writes += 1

    def retrieve_memory(self, **kw):
        return []

    def retrieve_patterns(self, **kw):
        return []


def _settings(tmp_path):
    return Settings(mode="local", db_path=tmp_path / "k.db", key_file=tmp_path / "key", secret_key=None,
                    judge_api_key="k", attacker_api_key="k")


def _run(tmp_path):
    store = TargetStore(tmp_path / "k.db", Vault(Fernet.generate_key()))
    target = store.create_target(name="A", url="http://t/chat", method="POST", headers=[],
                                 body_template='{"message":"{{prompt}}"}', response_path="$.reply",
                                 terms_version="6")
    experiment = store.create_experiment(
        target_id=target.id, mode="single_turn", families=["direct_injection"], reps=1,
        seed_prompt_ids={"direct_injection": "dir-001"},
        max_runs=50, token_budget_total=500_000, wall_clock_s=3600, arm_a=COLD, arm_b=WARM)
    experience = _Experience()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"reply": "the agent held"}))
    asyncio.run(run_experiment(store, experiment_id=experiment.id, settings=_settings(tmp_path),
                               library=fixture_library(), experience=experience, transport=transport,
                               make_judge=lambda model: StubJudge(verdict="failed")))
    return store, store.get_experiment(experiment.id), experience


def test_cold_arm_does_not_write_back_but_warm_arm_does(tmp_path):
    store, experiment, experience = _run(tmp_path)
    arms = {a.label: a for a in experiment.arms}
    cold_runs = store.arm_runs(experiment.id, arms["A"].id)
    warm_runs = store.arm_runs(experiment.id, arms["B"].id)
    assert all(run.memory_written is None for run in cold_runs)    # cold: write-back skipped (not warmed)
    assert all(run.memory_written is True for run in warm_runs)    # warm: wrote back
    assert experience.writes >= 1                                  # only the warm arm wrote


def test_run_order_is_recorded(tmp_path):
    _, experiment, _ = _run(tmp_path)
    assert {a.label: a.run_order for a in experiment.arms} == {"A": 1, "B": 2}
