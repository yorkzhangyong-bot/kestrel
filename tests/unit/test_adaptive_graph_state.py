"""The adaptive loop's typed state: the conversation is appended through a reducer (a node returns only its
turn's delta) and `turns_used` counts the turns driven
(003/FR-005: the loop reads the conversation so far each turn; 003/FR-010: the turn accounting the caps rest on).

Drives the module-level compiled live graph directly, with stubbed dependencies in its runtime context - no
network, no model, no attack text (placeholder messages only). The one secrets-handling check (001/FR-022) is that
no repr of the runtime context can show the placeholder auth value it carries.
"""
from __future__ import annotations

import asyncio

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from kestrel.attack.graph import LIVE_GRAPH, _initial_state, _LiveDeps, _State
from kestrel.attacks.library import AttackPrompt
from kestrel.connection.tester import ResolvedSettings, TestOutcome as SendOutcome
from kestrel.evidence.checker import EvidenceChecker
from tests.support import StubAttacker, StubJudge

FEATURE = "003"

SEED = AttackPrompt(id="spl-002", title="t", text="<seed opening>", family="system_prompt_leak",
                    owasp_category="LLM07: System Prompt Leakage", source="x", source_url="x", licence="x")
RESOLVED = ResolvedSettings(url="http://t/chat", method="POST", headers=(("X-API-Key", "test-key-123"),),
                            body_template='{"message": "{{prompt}}"}', response_path="$.reply")
SECRET = "test-key-123"   # the placeholder auth value every offline test registers


class StubStore:
    """The store calls a record node makes, kept as a list of the turn positions written. Feature 014: the lifted
    record step now calls has_turn/add_turn_with_evidence instead of add_turn/add_evidence directly (research D6)
    - this stub gains both, a stub gaining the store methods its own code under test now calls, never a behaviour
    change to what this test itself asserts (plan.md's own pre-existing-test-edit list)."""

    def __init__(self):
        self.turns: list[int] = []
        self.evidence: list[int] = []

    def add_turn(self, run_id, *, position, **_fields):
        self.turns.append(position)

    def add_evidence(self, run_id, items):
        self.evidence.append(len(items))

    def has_turn(self, run_id, position):
        return position in self.turns

    def add_turn_with_evidence(self, run_id, *, position, evidence_items=(), **_fields):
        self.turns.append(position)
        if evidence_items:
            self.evidence.append(len(evidence_items))


def numbered_sender(*, fail_at: int | None = None):
    """A sender whose n-th reply is `<agent reply n>`, or a failed send at `fail_at`."""
    count = {"n": 0}

    async def send(resolved, **_kwargs):
        count["n"] += 1
        n = count["n"]
        if n == fail_at:
            return SendOutcome(ok=False, step="endpoint_error", message="Status 502", reply_text=None,
                              reply_truncated=False, status_code=502)
        reply = f"<agent reply {n}>"
        return SendOutcome(ok=True, step="success", message="Connection works.", reply_text=reply,
                          reply_truncated=False, status_code=200)
    return send


def make_deps(*, store, sender, judge, attacker, max_turns=3):
    return _LiveDeps(store=store, run_id=1, resolved=RESOLVED, secrets=[SECRET], mode="local",
                     sender=sender, transport=None, resolver=None, judge=judge, judge_prompt="judge@1",
                     judge_prompt_id="judge", judge_prompt_version="1",
                     checker=EvidenceChecker.canary_only([], family=SEED.family),
                     max_turns=max_turns, token_budget=40000, deadline=1300.0, clock=lambda: 1000.0,
                     seed_prompt=SEED, opening=SEED.text, attacker=attacker, hint_provider=None,
                     attacker_prompt="attacker:system_prompt_leak@1", attacker_prompt_id="attacker:system_prompt_leak",
                     attacker_prompt_version="1")


def drive(deps):
    return asyncio.run(LIVE_GRAPH.ainvoke(_initial_state(), {"recursion_limit": 50}, context=deps))


def test_the_conversation_holds_each_turns_pair_once_in_order_and_turns_used_counts_the_turns():   # FR-005, FR-010
    store = StubStore()
    final = drive(make_deps(store=store, sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                            attacker=StubAttacker(), max_turns=3))

    assert final["conversation"] == [("attacker", "<seed opening>"), ("agent", "<agent reply 1>"),
                                     ("attacker", "<attacker turn 2>"), ("agent", "<agent reply 2>"),
                                     ("attacker", "<attacker turn 3>"), ("agent", "<agent reply 3>")]
    assert final["turns_used"] == 3 and store.turns == [1, 2, 3]
    assert final["outcome"].stopping_condition == "turn_cap"


def test_a_failed_send_appends_the_message_alone_and_nothing_is_doubled_or_lost():   # FR-005, FR-010
    final = drive(make_deps(store=StubStore(), sender=numbered_sender(fail_at=2), judge=StubJudge(verdict="failed"),
                            attacker=StubAttacker(), max_turns=3))

    assert final["conversation"] == [("attacker", "<seed opening>"), ("agent", "<agent reply 1>"),
                                     ("attacker", "<attacker turn 2>")]
    assert final["turns_used"] == 2
    assert final["outcome"].stopping_condition == "send_failed" and final["outcome"].failure_step == "endpoint_error"


def test_an_empty_delta_leaves_the_conversation_unchanged():   # FR-005
    """The reducer as wired into the state schema: a node that returns an empty delta, or no conversation key
    at all, leaves the recorded conversation exactly as it was."""
    def empty_delta(state: _State) -> _State:
        return {"conversation": [], "turns_used": state["turns_used"] + 1}

    def no_key(state: _State) -> _State:
        return {"turns_used": state["turns_used"] + 1}

    graph = StateGraph(_State)
    graph.add_node("empty", empty_delta)
    graph.add_node("silent", no_key)
    graph.add_edge(START, "empty")
    graph.add_edge("empty", "silent")
    graph.add_edge("silent", END)
    before = [("attacker", "<message one>"), ("agent", "<reply one>")]
    initial: _State = {**_initial_state(), "conversation": list(before)}

    final = asyncio.run(graph.compile().ainvoke(initial))

    assert final["conversation"] == before and final["turns_used"] == 2


def test_no_repr_of_the_runtime_context_shows_an_auth_value():   # 001/FR-022
    """The deps carry the target's auth values and LangGraph's `Runtime` repr includes its context, so neither
    repr may render the placeholder secret (the resolved target's own repr already hides it)."""
    deps = make_deps(store=StubStore(), sender=numbered_sender(), judge=StubJudge(), attacker=StubAttacker())
    runtime = Runtime(context=deps)

    assert SECRET not in repr(deps) and SECRET not in repr(runtime)
    assert SECRET not in repr(RESOLVED)
