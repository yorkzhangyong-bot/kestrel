"""Hard caps stop an experiment cleanly with partial results (feature 007). Traces 007/FR-008, 007/SC-004."""
import asyncio

import httpx
from cryptography.fernet import Fernet

from kestrel.experiments.engine import run_experiment
from kestrel.judge.verdict import ParsedVerdict
from kestrel.secrets import Vault
from kestrel.settings import Settings
from kestrel.store import TargetStore
from tests.support import StubJudge, fixture_library

FEATURE = "007"

ARM_A = {"attacker_model": "m-a", "judge_model": "j", "use_prior_experience": False,
         "turn_cap": 6, "token_budget": 40000, "write_back": False}
ARM_B = {"attacker_model": "m-b", "judge_model": "j", "use_prior_experience": True,
         "turn_cap": 6, "token_budget": 40000, "write_back": False}


class _TokenJudge:
    configured = True
    model = "j"

    def __init__(self, tokens):
        self._tokens = tokens

    async def judge(self, *, attack, reply, conversation=None, timeout=None):
        return ParsedVerdict("failed", "held", tokens=self._tokens)


class _Clock:
    def __init__(self, step):
        self.now = 0.0
        self.step = step

    def __call__(self):
        value = self.now
        self.now += self.step
        return value


def _experiment(tmp_path, *, max_runs=50, token_budget_total=500_000, wall_clock_s=3600, reps=2):
    store = TargetStore(tmp_path / "k.db", Vault(Fernet.generate_key()))
    target = store.create_target(name="A", url="http://t/chat", method="POST", headers=[],
                                 body_template='{"message":"{{prompt}}"}', response_path="$.reply",
                                 terms_version="6")
    experiment = store.create_experiment(
        target_id=target.id, mode="single_turn", families=["direct_injection"], reps=reps,
        seed_prompt_ids={"direct_injection": "dir-001"},
        max_runs=max_runs, token_budget_total=token_budget_total, wall_clock_s=wall_clock_s,
        arm_a=ARM_A, arm_b=ARM_B)
    return store, experiment.id


def _settings(tmp_path):
    return Settings(mode="local", db_path=tmp_path / "k.db", key_file=tmp_path / "key", secret_key=None,
                    judge_api_key="k", attacker_api_key="k")


def _reply():
    return httpx.MockTransport(lambda request: httpx.Response(200, json={"reply": "held"}))


def _go(store, experiment_id, tmp_path, *, judge=None, clock=None):
    kwargs = {}
    if clock is not None:
        kwargs["clock"] = clock
    asyncio.run(run_experiment(store, experiment_id=experiment_id, settings=_settings(tmp_path),
                               library=fixture_library(), experience=None, transport=_reply(),
                               make_judge=lambda model: judge or StubJudge(verdict="failed"), **kwargs))


def test_max_runs_stops_cleanly_with_partial_results(tmp_path):
    store, experiment_id = _experiment(tmp_path, max_runs=2, reps=2)
    _go(store, experiment_id, tmp_path)
    experiment = store.get_experiment(experiment_id)
    assert experiment.status == "stopped" and experiment.stopped_reason == "max_runs"
    assert store.experiment_progress(experiment_id)["completed"] == 2   # partial: stopped at the cap
    assert experiment.finished_at is not None


def test_token_budget_stops_cleanly(tmp_path):
    store, experiment_id = _experiment(tmp_path, token_budget_total=50, reps=2)
    _go(store, experiment_id, tmp_path, judge=_TokenJudge(100))
    experiment = store.get_experiment(experiment_id)
    assert experiment.status == "stopped" and experiment.stopped_reason == "token_budget"


def test_wall_clock_stops_cleanly(tmp_path):
    store, experiment_id = _experiment(tmp_path, wall_clock_s=150, reps=2)
    _go(store, experiment_id, tmp_path, clock=_Clock(step=100))
    experiment = store.get_experiment(experiment_id)
    assert experiment.status == "stopped" and experiment.stopped_reason == "wall_clock"
