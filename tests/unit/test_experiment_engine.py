"""The experiment engine runs arm A then arm B and records every run (feature 007).

Traces 007/FR-003, 007/FR-004, 007/FR-015. Stub judge/attacker and a MockTransport - no network, no attack text.
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

ARM_A = {"attacker_model": "m-a", "judge_model": "j", "use_prior_experience": False,
         "turn_cap": 6, "token_budget": 40000, "write_back": True}
ARM_B = {"attacker_model": "m-b", "judge_model": "j", "use_prior_experience": True,
         "turn_cap": 6, "token_budget": 40000, "write_back": True}


class _Experience:
    def write_memory(self, **kw): pass
    def write_pattern(self, **kw): pass
    def retrieve_memory(self, **kw): return []
    def retrieve_patterns(self, **kw): return []


def _settings(tmp_path) -> Settings:
    return Settings(mode="local", db_path=tmp_path / "k.db", key_file=tmp_path / "key", secret_key=None,
                    judge_api_key="k", attacker_api_key="k")


def _store_target(tmp_path):
    store = TargetStore(tmp_path / "k.db", Vault(Fernet.generate_key()))
    target = store.create_target(name="A", url="http://t/chat", method="POST", headers=[],
                                 body_template='{"message":"{{prompt}}"}', response_path="$.reply",
                                 terms_version="6")
    return store, target


def _reply(text):
    return httpx.MockTransport(lambda request: httpx.Response(200, json={"reply": text}))


def _run(store, experiment_id, *, transport, settings):
    asyncio.run(run_experiment(store, experiment_id=experiment_id, settings=settings,
                               library=fixture_library(), experience=_Experience(), transport=transport,
                               make_judge=lambda model: StubJudge(verdict="failed"),
                               make_attacker=None))


def test_runs_arm_a_then_b_and_records_links(tmp_path):
    store, target = _store_target(tmp_path)
    exp = store.create_experiment(
        target_id=target.id, mode="single_turn", families=["direct_injection", "system_prompt_leak"], reps=1,
        seed_prompt_ids={"direct_injection": "dir-001", "system_prompt_leak": "spl-001"},
        max_runs=50, token_budget_total=500_000, wall_clock_s=3600, arm_a=ARM_A, arm_b=ARM_B)
    _run(store, exp.id, transport=_reply("the agent held"), settings=_settings(tmp_path))

    got = store.get_experiment(exp.id)
    assert got.status == "finished" and got.stopped_reason == "completed"
    assert {a.label: a.run_order for a in got.arms} == {"A": 1, "B": 2}
    links = store.experiment_run_links(exp.id)
    assert len(links) == 4 and all(link.run_id is not None for link in links)   # 2 families x 1 rep x 2 arms


def test_failed_send_is_recorded_not_dropped(tmp_path):
    store, target = _store_target(tmp_path)
    exp = store.create_experiment(
        target_id=target.id, mode="single_turn", families=["direct_injection"], reps=1,
        seed_prompt_ids={"direct_injection": "dir-001"},
        max_runs=50, token_budget_total=500_000, wall_clock_s=3600, arm_a=ARM_A, arm_b=ARM_B)
    error_transport = httpx.MockTransport(lambda request: httpx.Response(500))
    _run(store, exp.id, transport=error_transport, settings=_settings(tmp_path))

    links = store.experiment_run_links(exp.id)
    assert len(links) == 2 and all(link.send_ok is False for link in links)   # both arms, send failed, kept
