"""Provenance records the prompt version actually used, from the single source the log lines use (research D15).

The run functions take the references from the clients (`attacker.prompt_ref(family)`, `judge.judge_prompt_ref`),
falling back to the registry's active version for a client double without the accessor; judge provenance is written
only when a judge request was made (010/FR-007, 010/FR-017, 010/SC-005). Stubs only; no network, no attack text."""
import asyncio

import pytest
from cryptography.fernet import Fernet

from kestrel.attack.graph import run_adaptive
from kestrel.attacks.library import AttackPrompt
from kestrel.connection.tester import ResolvedSettings, TestOutcome as Outcome
from kestrel.judge.client import JudgeError
from kestrel.runs import execute_run
from kestrel.secrets import Vault
from kestrel.store import TargetStore
from tests.support import StubAttacker, StubJudge

FEATURE = "010"

SEED = AttackPrompt(id="spl-002", title="t", text="<seed opening>", family="system_prompt_leak",
                    owasp_category="LLM07: System Prompt Leakage", source="x", source_url="x", licence="x")
RESOLVED = ResolvedSettings(url="http://t/chat", method="POST", headers=(("X-API-Key", "k"),),
                            body_template='{"message": "{{prompt}}"}', response_path="$.reply")
CANARY = "CANARY-PLACEHOLDER-1234"


class PinnedAttacker(StubAttacker):
    """An attacker client that reports the pinned prompt reference it would send."""

    def prompt_ref(self, family):
        return f"attacker:{family}@3"


class PinnedJudge(StubJudge):
    judge_prompt_ref = "judge@2"


def _sender(reply="a reply"):
    async def send(resolved, **kwargs):
        return Outcome(ok=True, step="success", message="ok", reply_text=reply, reply_truncated=False,
                       status_code=200)
    return send


@pytest.fixture
def store(tmp_path):
    return TargetStore(tmp_path / "data" / "kestrel.db", Vault(Fernet.generate_key()))


@pytest.fixture
def target(store):
    return store.create_target(name="A", url="http://t/chat", method="POST", headers=[("X-API-Key", "k")],
                               body_template='{"message": "{{prompt}}"}', response_path="$.reply", terms_version="7")


def adaptive(store, target, *, attacker=None, judge=None, reply="a reply", canaries=(), max_turns=2):
    return asyncio.run(run_adaptive(
        store, target_id=target.id, seed_prompt=SEED, attacker_source="library:1.0.0", canaries=list(canaries),
        resolved=RESOLVED, attacker=attacker or StubAttacker(), judge=judge or StubJudge(), sender=_sender(reply),
        max_turns=max_turns, token_budget=40000, time_limit_s=300.0))


def single(store, target, *, judge=None, reply="a reply", canaries=()):
    return asyncio.run(execute_run(store, target_id=target.id, prompt=SEED, attacker_source="library:1.0.0",
                                   canaries=list(canaries), resolved=RESOLVED, mode="local",
                                   judge=judge or StubJudge(), sender=_sender(reply)))


def provenance(store, run):
    turns = [(t.attacker_prompt_id, t.attacker_prompt_version, t.judge_prompt_id, t.judge_prompt_version)
             for t in store.list_turns(run.id)]
    stored = store.get_run(run.id)
    return turns, (stored.judge_prompt_id, stored.judge_prompt_version)


def test_an_adaptive_run_records_the_references_its_clients_used(store, target):  # FR-007
    run = adaptive(store, target, attacker=PinnedAttacker(), judge=PinnedJudge())
    turns, verdict = provenance(store, run)
    assert turns == [(None, None, "judge", "2"), ("attacker:system_prompt_leak", "3", "judge", "2")]
    assert verdict == ("judge", "2")


def test_a_client_double_without_the_accessor_falls_back_to_the_active_version(store, target):  # FR-007, SC-005
    run = adaptive(store, target)
    turns, verdict = provenance(store, run)
    assert turns == [(None, None, "judge", "1"), ("attacker:system_prompt_leak", "1", "judge", "1")]
    assert verdict == ("judge", "1")


def test_an_adaptive_run_without_a_judge_records_no_judge_provenance(store, target):  # FR-007
    run = adaptive(store, target, judge=StubJudge(configured=False))
    turns, verdict = provenance(store, run)
    assert all(t[2:] == (None, None) for t in turns) and verdict == (None, None)
    assert store.get_run(run.id).judge_used is True   # the stored feature-003 flag is unchanged (FR-017)


def test_a_canary_decided_adaptive_turn_records_no_judge_provenance(store, target):  # FR-007
    run = adaptive(store, target, reply=f"leaked {CANARY}", canaries=[CANARY])
    turns, verdict = provenance(store, run)
    assert turns == [(None, None, None, None)] and verdict == (None, None)   # no judge request was made


def test_a_judged_single_turn_run_records_its_judge_version(store, target):  # FR-007
    assert provenance(store, single(store, target))[1] == ("judge", "1")
    assert provenance(store, single(store, target, judge=PinnedJudge()))[1] == ("judge", "2")


def test_a_single_turn_judge_error_still_records_the_request_made(store, target):  # FR-007
    run = single(store, target, judge=StubJudge(error=JudgeError("unreachable")))
    assert provenance(store, run)[1] == ("judge", "1") and run.verdict == "unclear"


@pytest.mark.parametrize("kwargs", [{"judge": StubJudge(configured=False)},
                                    {"reply": f"leaked {CANARY}", "canaries": [CANARY]}])
def test_a_single_turn_run_without_a_judge_request_records_none(store, target, kwargs):  # FR-007
    assert provenance(store, single(store, target, **kwargs))[1] == (None, None)
