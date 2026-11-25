"""Time spent is set, not accumulated, in every node's own delta, anchored to when the current invocation began
(014/FR-016, SC-005, research D24)."""
import asyncio
import dataclasses

import pytest
from cryptography.fernet import Fernet

from kestrel.attack.graph import LIVE_GRAPH, _initial_state, _time_spent
from kestrel.checkpointing import KestrelCheckpointSaver, classify
from kestrel.secrets import Vault
from kestrel.store import TargetStore
from tests.unit.test_adaptive_graph_state import make_deps, numbered_sender, StubStore
from tests.support import StubAttacker, StubJudge

FEATURE = "014"


class FakeClock:
    """A controllable monotonic-style clock: starts at `start`, advances only when told to."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def store(tmp_path) -> TargetStore:
    return TargetStore(tmp_path / "kestrel.db", Vault(Fernet.generate_key()))


def test_time_spent_is_the_anchor_formula_not_an_increment():  # FR-016, research D24
    clock = FakeClock(1000.0)
    deps = dataclasses.replace(make_deps(store=StubStore(), sender=numbered_sender(), judge=StubJudge(),
                                        attacker=StubAttacker()),
                               clock=clock, time_spent_at_invocation_start=50.0, invocation_start=1000.0)
    assert _time_spent(deps) == 50.0   # no time elapsed yet: spent-before + (now - start) == spent-before
    clock.advance(7.5)
    assert _time_spent(deps) == 57.5   # recomputed fresh from the same two anchors, never incremented


def test_an_uninterrupted_runs_own_deadline_is_byte_identical_to_todays_formula():  # FR-016, SC-005
    # time_spent_at_invocation_start is 0.0 for a fresh claim, so deadline = clock() + time_limit_s exactly as
    # before this feature; invocation_start equals clock() at construction, so time_spent_s starts at 0.0 too.
    clock = FakeClock(2000.0)
    deps = dataclasses.replace(make_deps(store=StubStore(), sender=numbered_sender(), judge=StubJudge(),
                                        attacker=StubAttacker()),
                               clock=clock, deadline=clock() + 300.0, invocation_start=clock())
    assert deps.deadline == 2300.0
    assert _time_spent(deps) == 0.0


def test_several_turns_within_one_continuous_invocation_never_double_count(store):  # FR-016, research D24
    # A clock that never advances: if any node incremented time_spent_s instead of recomputing it fresh, running
    # three turns' worth of nodes would still grow it. It must stay at exactly 0.0 throughout.
    deps = make_deps(store=StubStore(), sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                     attacker=StubAttacker(), max_turns=3)
    final = asyncio.run(LIVE_GRAPH.ainvoke(_initial_state(), {"recursion_limit": 50}, context=deps))
    assert final["turns_used"] == 3
    assert final["time_spent_s"] == 0.0


def test_a_simulated_gap_between_invocations_does_not_cause_an_immediate_timeout(store):  # FR-016, SC-005
    clock = FakeClock(1000.0)

    def slow_sender(*, fail_at=None):
        async def send(resolved, **_kwargs):
            clock.advance(10.0)   # a node's own body takes some real time
            from kestrel.connection.tester import TestOutcome
            return TestOutcome(ok=True, step="success", message="ok", reply_text="<reply>",
                               reply_truncated=False, status_code=200)
        return send

    deps = dataclasses.replace(
        make_deps(store=StubStore(), sender=slow_sender(), judge=StubJudge(verdict="failed"),
                 attacker=StubAttacker(), max_turns=1),
        clock=clock, deadline=clock() + 300.0, invocation_start=clock())
    final = asyncio.run(LIVE_GRAPH.ainvoke(_initial_state(), {"recursion_limit": 50}, context=deps))
    spent_first_segment = final["time_spent_s"]
    assert 0 < spent_first_segment < 300   # genuinely spent some time, nowhere near the cap

    # Simulate a long gap: nothing runs, the clock just advances past the configured limit.
    clock.advance(10_000.0)

    # A resume/decision's own deps construction (research D24): deadline = clock() + (limit - time already spent).
    resumed_deps = dataclasses.replace(deps, time_spent_at_invocation_start=spent_first_segment,
                                       invocation_start=clock(), deadline=clock() + (300.0 - spent_first_segment))
    assert resumed_deps.remaining() == pytest.approx(300.0 - spent_first_segment)
    assert resumed_deps.remaining() > 0   # the gap itself never counts against the time limit


def test_a_run_already_over_its_time_limit_at_resume_ends_at_the_cap_on_the_next_check():  # FR-016, SC-005
    from kestrel.attack.graph import _decide_next
    clock = FakeClock(5000.0)
    deps = dataclasses.replace(
        make_deps(store=StubStore(), sender=numbered_sender(), judge=StubJudge(), attacker=StubAttacker(),
                 max_turns=99),
        clock=clock, time_spent_at_invocation_start=400.0, invocation_start=clock(),
        deadline=clock() + (300.0 - 400.0))   # already 100s past the 300s limit the moment this invocation begins
    assert deps.remaining() < 0
    state = {"turns_used": 1, "tokens_used": 0, "judge_used": False, "last_verdict": "unclear",
             "last_reason": None}
    delta = _decide_next(state, max_turns=deps.max_turns, token_budget=deps.token_budget,
                         remaining=deps.remaining)
    assert delta["outcome"].stopping_condition == "time_limit"


def test_the_attacker_nodes_own_delta_persists_drafting_time_before_send_ever_runs(store):
    # 014/FR-016, SC-005: the approve-node pause case, proved at the primitive level (part 1 has no approve node
    # yet) - cut right after `attacker` completes but before the next node (`send`, in part 1's own topology)
    # runs. The attacker node's own delta must already have set an up-to-date time_spent_s reflecting the
    # drafting time, durably committed (synchronous durability) before send ever gets a chance to run - never
    # left at the previous turn's own stale value.
    clock = FakeClock(3000.0)

    class _Boom(Exception):
        pass

    async def drafts_turn_two(*, conversation, family, progress=None, hints=None, timeout=None):
        from kestrel.attack.attacker import AttackerReply
        clock.advance(2.5)   # drafting the message takes some real time
        return AttackerReply(message="<attacker turn 2>", tokens=10)

    attacker = StubAttacker()
    attacker.next_message = drafts_turn_two

    def crashing_sender():
        calls = {"n": 0}

        async def send(resolved, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:   # turn 1's own opening message sends normally
                from kestrel.connection.tester import TestOutcome
                return TestOutcome(ok=True, step="success", message="ok", reply_text="<reply 1>",
                                   reply_truncated=False, status_code=200)
            raise _Boom("simulated crash during send, right after attacker's own turn-2 delta committed")
        return send

    saver = KestrelCheckpointSaver(store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = dataclasses.replace(
        make_deps(store=StubStore(), sender=crashing_sender(), judge=StubJudge(verdict="failed"), attacker=attacker,
                 max_turns=3),
        clock=clock, deadline=clock() + 300.0, invocation_start=clock())
    config = {"configurable": {"thread_id": "555"}}

    async def go():
        with pytest.raises(_Boom):
            await copied.ainvoke(_initial_state(), config, context=deps, durability="sync")
        return await classify(copied, 555, leased=False)

    status = asyncio.run(go())
    assert status.from_step == "send"   # attacker's own turn-2 delta already committed; send is next
    state = status.snapshot.values
    assert state["pending_message"] == "<attacker turn 2>"
    assert state["time_spent_s"] == pytest.approx(2.5, abs=1e-6)   # turn 2's own attacker delta already committed
    assert state["turn_time_spent_at_start"] == pytest.approx(state["time_spent_s"] - 2.5, abs=1e-6)
