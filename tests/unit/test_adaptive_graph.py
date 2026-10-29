"""The adaptive attacker/judge loop (contracts/adaptive-loop.md). Stub attacker, judge and sender — no network.

No attack text: the stub attacker emits placeholder messages; the stubs drive the control flow being tested.
"""
import asyncio

import pytest
from cryptography.fernet import Fernet

from kestrel.attack.attacker import AttackerError, AttackerReply
from kestrel.attack.graph import run_adaptive
from kestrel.attacks.library import AttackPrompt
from kestrel.connection.tester import ResolvedSettings, TestOutcome as Outcome
from kestrel.judge.client import JudgeError
from kestrel.judge.verdict import ParsedVerdict
from kestrel.secrets import Vault
from kestrel.store import TargetStore

FEATURE = "003"

SEED = AttackPrompt(id="spl-002", title="t", text="<seed opening>", family="system_prompt_leak",
                    owasp_category="LLM07: System Prompt Leakage", source="x", source_url="x", licence="x")
RESOLVED = ResolvedSettings(url="http://t/chat", method="POST", headers=(("X-API-Key", "test-key-123"),),
                            body_template='{"message": "{{prompt}}"}', response_path="$.reply")
SRC = "library:1.0.0"


@pytest.fixture
def store(tmp_path) -> TargetStore:
    return TargetStore(tmp_path / "data" / "kestrel.db", Vault(Fernet.generate_key()))


@pytest.fixture
def target(store):
    return store.create_target(name="A", url="http://t/chat", method="POST", headers=[("X-API-Key", "test-key-123")],
                               body_template='{"message": "{{prompt}}"}', response_path="$.reply", terms_version="3")


class StubAttacker:
    """Emits a placeholder message each turn; records what it was shown; can be told to fail."""
    def __init__(self, error=None, tokens=100):
        self.model = "stub/attacker"
        self.configured = True
        self._error, self._tokens = error, tokens
        self.seen = []

    async def next_message(self, *, conversation, family, progress=None, hints=None, timeout=None):
        self.seen.append({"conversation": conversation, "progress": progress, "hints": hints, "timeout": timeout})
        if self._error is not None:
            raise self._error
        return AttackerReply(message=f"<attacker turn {len(conversation)//2 + 1}>", tokens=self._tokens)


class StubJudge:
    def __init__(self, verdict="failed", progress="getting closer", error=None, configured=True, tokens=120):
        self.model = "stub/judge"
        self.configured = configured
        self._v, self._p, self._err, self._tokens = verdict, progress, error, tokens
        self.calls = []

    async def judge(self, *, attack, reply, conversation=None, timeout=None):
        self.calls.append({"reply": reply, "conversation": conversation, "timeout": timeout})
        if self._err is not None:
            raise self._err
        return ParsedVerdict(self._v, "reason", progress=self._p, tokens=self._tokens)


def sender_returning(*outcomes, record=None, clock=None, step_s=0.0):
    """A stub for run_test. Returns the given outcomes in turn; last repeats. May advance a fake clock."""
    seq = list(outcomes)

    async def send(resolved, **kwargs):
        if record is not None:
            record.append(kwargs)
        if clock is not None and step_s:
            clock.advance(step_s)
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return send


class FakeClock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def advance(self, by): self.t += by


def ok(reply="an ordinary reply", truncated=False):
    return Outcome(ok=True, step="success", message="Connection works.", reply_text=reply,
                       reply_truncated=truncated, status_code=200)


def run(store, target, *, attacker, judge, sender, canaries=(), max_turns=6, token_budget=40000,
        time_limit_s=300.0, clock=None):
    return asyncio.run(run_adaptive(
        store, target_id=target.id, seed_prompt=SEED, attacker_source=SRC, canaries=list(canaries),
        resolved=RESOLVED, attacker=attacker, judge=judge, sender=sender, max_turns=max_turns,
        token_budget=token_budget, time_limit_s=time_limit_s, clock=clock or FakeClock()))


# --- success paths ---

def test_a_canary_at_a_turn_ends_succeeded_by_hard_evidence_without_the_judge(store, target):
    judge = StubJudge(verdict="failed")  # would disagree, must not be consulted that turn
    r = run(store, target, canaries=["KESTREL-CANARY-7Q4M2X"], judge=judge,
            attacker=StubAttacker(), sender=sender_returning(ok("leak KESTREL-CANARY-7Q4M2X")))
    assert r.verdict == "succeeded" and r.hard_evidence is True and r.succeeded_turn == 1
    assert r.stopping_condition == "succeeded" and r.judge_used is False
    assert judge.calls == []


def test_a_judge_succeeded_ends_the_run_not_as_hard_evidence(store, target):
    r = run(store, target, judge=StubJudge(verdict="succeeded"), attacker=StubAttacker(),
            sender=sender_returning(ok()))
    assert r.verdict == "succeeded" and r.hard_evidence is False and r.judge_used is True
    assert r.succeeded_turn == 1 and r.stopping_condition == "succeeded"


def test_turn_one_uses_the_seed_without_calling_the_attacker(store, target):
    attacker = StubAttacker()
    run(store, target, judge=StubJudge(verdict="succeeded"), attacker=attacker, sender=sender_returning(ok()))
    assert attacker.seen == []  # the opening was the library seed, not an attacker call
    assert store.list_turns.__self__ is store  # sanity


def test_the_seed_is_the_first_sent_prompt(store, target):
    sent = []
    run(store, target, judge=StubJudge(verdict="succeeded"), attacker=StubAttacker(),
        sender=sender_returning(ok(), record=sent))
    assert sent[0]["prompt"] == SEED.text


# --- caps (FR-010, FR-011, FR-012) ---

def test_the_turn_cap_stops_the_run(store, target):
    r = run(store, target, judge=StubJudge(verdict="failed"), attacker=StubAttacker(),
            sender=sender_returning(ok()), max_turns=3)
    assert r.turns_used == 3 and r.stopping_condition == "turn_cap"
    assert r.verdict == "failed" and r.hard_evidence is False
    assert len(store.list_turns(r.id)) == 3


def test_the_token_budget_stops_the_run(store, target):
    # Each turn spends ~220 tokens (attacker 100 + judge 120); a 300 budget allows ~1 turn.
    r = run(store, target, judge=StubJudge(verdict="failed", tokens=120), attacker=StubAttacker(tokens=100),
            sender=sender_returning(ok()), token_budget=300, max_turns=99)
    assert r.stopping_condition == "token_budget"
    assert r.tokens_used <= 300 + 220  # stopped before starting a turn once the budget was reached


def test_the_time_limit_stops_the_run(store, target):
    clock = FakeClock()
    sender = sender_returning(ok(), clock=clock, step_s=40.0)  # each send eats 40s
    r = run(store, target, judge=StubJudge(verdict="failed"), attacker=StubAttacker(),
            sender=sender, time_limit_s=90.0, max_turns=99, clock=clock)
    assert r.stopping_condition == "time_limit"


# --- failures ---

def test_a_failed_send_ends_the_run_with_the_step_and_no_further_turns(store, target):
    failure = Outcome(ok=False, step="unreachable", message="Unreachable.")
    r = run(store, target, judge=StubJudge(), attacker=StubAttacker(), sender=sender_returning(failure))
    assert r.failure_step == "unreachable" and r.verdict is None
    assert r.stopping_condition == "send_failed" and r.judge_used is False
    assert len(store.list_turns(r.id)) == 1  # the one attempted turn is recorded


def test_an_attacker_failure_ends_the_run_unclear(store, target):
    # The attacker is only called from turn two, so the first judge must say "failed" to reach it.
    r = run(store, target, judge=StubJudge(verdict="failed"),
            attacker=StubAttacker(error=AttackerError("no credit")), sender=sender_returning(ok()), max_turns=6)
    assert r.verdict == "unclear" and r.stopping_condition == "attacker_failed"


def test_a_judge_failure_lets_the_run_continue_then_ends_unclear(store, target):
    r = run(store, target, judge=StubJudge(error=JudgeError("rate limited")), attacker=StubAttacker(),
            sender=sender_returning(ok()), max_turns=2)
    assert r.verdict == "unclear" and r.judge_used is True and r.judge_model == "stub/judge"


# --- invariants (SC-002, SC-005, Principle IV) ---

def test_every_path_ends_with_a_verdict_or_a_failure_step(store):
    scenarios = [
        dict(canaries=["KESTREL-CANARY-7Q4M2X"], judge=StubJudge(), attacker=StubAttacker(),
             sender=sender_returning(ok("has KESTREL-CANARY-7Q4M2X"))),
        dict(judge=StubJudge(verdict="succeeded"), attacker=StubAttacker(), sender=sender_returning(ok())),
        dict(judge=StubJudge(verdict="failed"), attacker=StubAttacker(), sender=sender_returning(ok()), max_turns=2),
        dict(judge=StubJudge(), attacker=StubAttacker(),
             sender=sender_returning(Outcome(ok=False, step="timed_out", message="x"))),
    ]
    for i, sc in enumerate(scenarios):
        t = store.create_target(name=f"T{i}", url="http://t/chat", method="POST",
                                headers=[("X-API-Key", "k")], body_template='{"message": "{{prompt}}"}',
                                response_path="$.reply", terms_version="3")
        r = run(store, t, clock=FakeClock(), **sc)
        assert (r.verdict is not None) or (r.failure_step is not None), sc
        assert r.stopping_condition is not None


def test_hard_evidence_is_never_set_from_a_judge_answer(store, target):
    r = run(store, target, judge=StubJudge(verdict="succeeded"), attacker=StubAttacker(), sender=sender_returning(ok()))
    assert r.hard_evidence is False  # the judge said succeeded, but only a canary is hard evidence


def test_the_stored_run_records_the_attacker_model_and_budgets(store, target):
    r = run(store, target, judge=StubJudge(verdict="failed"), attacker=StubAttacker(), sender=sender_returning(ok()),
            max_turns=2, token_budget=40000, time_limit_s=300.0)
    assert r.mode == "adaptive" and r.attacker_model == "stub/attacker"
    assert r.turn_budget == 2 and r.token_budget == 40000 and r.time_limit_s == 300
    assert r.attacker_source == SRC
