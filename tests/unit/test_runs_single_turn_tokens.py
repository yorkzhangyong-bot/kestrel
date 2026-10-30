"""A single-turn run records the judge's tokens (feature 007). Traces 007/FR-006.

Enables mean tokens / cost for single-turn arms: the judge already returns ParsedVerdict.tokens; execute_run just
threads it into the run record. A canary hit (judge not called) records 0 tokens.
"""
import asyncio

from cryptography.fernet import Fernet

from kestrel.attacks.library import AttackPrompt
from kestrel.connection.tester import ResolvedSettings, TestOutcome as Outcome
from kestrel.judge.verdict import ParsedVerdict
from kestrel.runs import execute_run
from kestrel.secrets import Vault
from kestrel.store import TargetStore

FEATURE = "007"

PROMPT = AttackPrompt(id="dir-001", title="t", text="<p>", family="direct_injection",
                      owasp_category="LLM01: Prompt Injection", source="x", source_url="x", licence="x")
RESOLVED = ResolvedSettings(url="http://t/chat", method="POST", headers=(),
                            body_template='{"m":"{{prompt}}"}', response_path="$.reply")
CANARY = "CANARY-TOKEN-XYZ"


class _Judge:
    configured = True
    model = "google/gemini-3.8-flash"

    def __init__(self, tokens: int) -> None:
        self._tokens = tokens

    async def judge(self, *, attack, reply, conversation=None, timeout=None):
        return ParsedVerdict("failed", "The agent held.", tokens=self._tokens)


def _target(tmp_path):
    store = TargetStore(tmp_path / "k.db", Vault(Fernet.generate_key()))
    target = store.create_target(name="A", url="http://t/chat", method="POST", headers=[],
                                 body_template='{"m":"{{prompt}}"}', response_path="$.reply", terms_version="6")
    return store, target.id


def _sender(reply: str):
    async def send(resolved, **kwargs):
        return Outcome(ok=True, step="success", message="ok", reply_text=reply)
    return send


def test_single_turn_records_judge_tokens(tmp_path):
    store, tid = _target(tmp_path)
    run = asyncio.run(execute_run(store, target_id=tid, prompt=PROMPT, attacker_source="library:1",
                                  canaries=[CANARY], resolved=RESOLVED, mode="local",
                                  judge=_Judge(137), sender=_sender("no marker here")))
    assert run.verdict == "failed" and run.tokens_used == 137


def test_canary_hit_records_zero_tokens(tmp_path):
    store, tid = _target(tmp_path)
    run = asyncio.run(execute_run(store, target_id=tid, prompt=PROMPT, attacker_source="library:1",
                                  canaries=[CANARY], resolved=RESOLVED, mode="local",
                                  judge=_Judge(137), sender=_sender(f"it leaked {CANARY} oops")))
    assert run.verdict == "succeeded" and run.hard_evidence is True and run.tokens_used == 0
