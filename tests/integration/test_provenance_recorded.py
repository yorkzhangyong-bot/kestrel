"""Feature 009: an adaptive run records, on each turn and on the verdict, which prompt version produced it — read
straight from the stored rows (009/FR-003, 009/SC-001). Stub attacker/judge/sender; no network, no attack text."""
import asyncio

import pytest
from cryptography.fernet import Fernet

from kestrel import prompt_registry as pr
from kestrel.attack.attacker import AttackerReply
from kestrel.attack.graph import run_adaptive
from kestrel.attacks.library import AttackPrompt
from kestrel.connection.tester import ResolvedSettings, TestOutcome as Outcome
from kestrel.judge.verdict import ParsedVerdict
from kestrel.secrets import Vault
from kestrel.store import TargetStore

FEATURE = "009"

SEED = AttackPrompt(id="spl-002", title="t", text="<seed opening>", family="system_prompt_leak",
                    owasp_category="LLM07: System Prompt Leakage", source="x", source_url="x", licence="x")
RESOLVED = ResolvedSettings(url="http://t/chat", method="POST", headers=(("X-API-Key", "k"),),
                            body_template='{"message": "{{prompt}}"}', response_path="$.reply")


class StubAttacker:
    model = "stub/attacker"
    configured = True

    async def next_message(self, *, conversation, family, progress=None, hints=None, timeout=None):
        return AttackerReply(message=f"<turn {len(conversation) // 2 + 1}>", tokens=10)


class StubJudge:
    model = "stub/judge"
    configured = True

    async def judge(self, *, attack, reply, conversation=None, timeout=None):
        return ParsedVerdict("failed", "reason", progress="closer", tokens=10)


def _sender(outcome):
    async def send(resolved, **kwargs):
        return outcome
    return send


def _run(store, target):
    return asyncio.run(run_adaptive(
        store, target_id=target.id, seed_prompt=SEED, attacker_source="library:1.0.0", canaries=[],
        resolved=RESOLVED, attacker=StubAttacker(), judge=StubJudge(),
        sender=_sender(Outcome(ok=True, step="success", message="ok", reply_text="a reply",
                               reply_truncated=False, status_code=200)),
        max_turns=2, token_budget=40000, time_limit_s=300.0))


@pytest.fixture
def store(tmp_path):
    return TargetStore(tmp_path / "data" / "kestrel.db", Vault(Fernet.generate_key()))


@pytest.fixture
def target(store):
    return store.create_target(name="A", url="http://t/chat", method="POST", headers=[("X-API-Key", "k")],
                               body_template='{"message": "{{prompt}}"}', response_path="$.reply", terms_version="7")


def _turns(store, run_id):
    with store.connect() as db:
        return db.execute(
            "SELECT position, attacker_prompt_id, attacker_prompt_version, judge_prompt_id, judge_prompt_version"
            " FROM run_turns WHERE run_id=? ORDER BY position", (run_id,)).fetchall()


def test_each_turn_and_the_verdict_record_their_prompt_version(store, target):  # 009/FR-003, 009/SC-001
    run = _run(store, target)
    rows = _turns(store, run.id)
    assert len(rows) == 2
    # Turn 1 is the library seed: no attacker prompt; the judge ran, so its version is recorded.
    assert rows[0]["attacker_prompt_id"] is None and rows[0]["attacker_prompt_version"] is None
    assert rows[0]["judge_prompt_id"] == "judge" and rows[0]["judge_prompt_version"] == "1.0.0"
    # Turn 2 is produced by the attacker model for this family.
    assert rows[1]["attacker_prompt_id"] == "attacker:system_prompt_leak"
    assert rows[1]["attacker_prompt_version"] == "1.0.0"
    assert rows[1]["judge_prompt_id"] == "judge" and rows[1]["judge_prompt_version"] == "1.0.0"
    # The run's verdict records the judge prompt version.
    with store.connect() as db:
        row = db.execute("SELECT judge_prompt_id, judge_prompt_version FROM runs WHERE id=?", (run.id,)).fetchone()
    assert row["judge_prompt_id"] == "judge" and row["judge_prompt_version"] == "1.0.0"


def test_every_recorded_version_exists_in_the_registry(store, target):  # 009/SC-001
    run = _run(store, target)
    for row in _turns(store, run.id):
        if row["attacker_prompt_id"]:
            assert pr.has(row["attacker_prompt_id"], row["attacker_prompt_version"])
        if row["judge_prompt_id"]:
            assert pr.has(row["judge_prompt_id"], row["judge_prompt_version"])
