"""The approve node, driven through the real production live-graph copy with the real `KestrelCheckpointSaver`
(014/FR-018, FR-019, FR-021, FR-022, FR-048, FR-052, research D4, D5, D7, D24).

Turn 1 never pauses; the first pause carries the exact drafted message; a bare re-invoke with nothing to resume
reproduces the identical pause with no new attacker call; a validated, targeted resume (`Command(resume={id:
"approve"})`) sends and pauses again at the next turn; "Run to end" flips the flag off and runs unattended; the
node reads its own flag from the state with a default, never from `_LiveDeps`, so a checkpoint (or experiment
repetition's own initial state) that lacks the field is still readable and the flag is never re-read from the
claim-time column on a resume. Part 2's own `test_from_step` reinforcement (FR-052): a completed `attacker` task
now routes to `approve`, never `send` directly - read from the compiled graph's own routing write, never a
hand-written table that cannot represent a node added to the topology.
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest
from cryptography.fernet import Fernet
from langgraph.types import Command

from kestrel import checkpointing
from kestrel.attack.graph import LIVE_GRAPH, _initial_state
from kestrel.checkpointing import KestrelCheckpointSaver, classify, thread_config
from kestrel.secrets import Vault
from kestrel.store import TargetStore
from tests.support import StubAttacker, StubJudge
from tests.unit.test_adaptive_graph_state import SEED, StubStore, make_deps, numbered_sender
from tests.unit.test_start_up_sweep_classification import _FailingPutSaver

FEATURE = "014"


@pytest.fixture
def real_store(tmp_path) -> TargetStore:
    return TargetStore(tmp_path / "kestrel.db", Vault(Fernet.generate_key()))


def _deps(attacker, *, run_id=1, max_turns=4):
    """A live deps object claiming "Ask before each turn" - the run's own column value, never what the approve
    node itself reads (it reads the state, which "Run to end" flips off)."""
    return dataclasses.replace(
        make_deps(store=StubStore(), sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                  attacker=attacker, max_turns=max_turns),
        run_id=run_id, ask_before_each_turn=True)


def _initial(*, ask: bool) -> dict:
    """The run's initial state, seeded exactly as `run_adaptive` seeds it at claim: with the flag only when the
    checkbox was ticked (research D5)."""
    state = _initial_state()
    if ask:
        state["ask_before_each_turn"] = True
    return state


def _paused_at(copied, run_id: int) -> checkpointing.Paused:
    status = asyncio.run(classify(copied, run_id, leased=False))
    assert isinstance(status, checkpointing.Paused)
    return status


def test_turn_one_is_sent_without_pausing_and_the_first_pause_carries_the_drafted_message(real_store):
    # 014/FR-019: turn 1 (the library seed) is sent without pausing; from turn 2 onward the attacker-drafted
    # message is held back, and the pause names that exact drafted message.
    saver = KestrelCheckpointSaver(real_store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    attacker = StubAttacker()
    deps = _deps(attacker)
    config = thread_config(1)

    final = asyncio.run(copied.ainvoke(_initial(ask=True), config, context=deps, durability="sync"))
    assert final["turns_used"] == 1            # turn 1 was sent and recorded, never paused
    assert final.get("outcome") is None        # the run paused, never finished
    assert len(attacker.calls) == 1            # turn 2 was drafted exactly once

    paused = _paused_at(copied, 1)
    assert paused.turn == 2
    assert paused.message == "<attacker turn 2>"   # the exact drafted message, held back from sending


def test_reinvoking_with_nothing_to_resume_reproduces_the_identical_pause_without_redrafting(real_store):
    # A bare re-invoke with nothing to resume is a read-only status re-check: the identical interrupt is
    # reproduced, with no new attacker call (turn 2's draft was already durably committed) and no side effect.
    saver = KestrelCheckpointSaver(real_store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    attacker = StubAttacker()
    deps = _deps(attacker)
    config = thread_config(1)

    async def go():
        await copied.ainvoke(_initial(ask=True), config, context=deps, durability="sync")
        again = await copied.ainvoke(None, config, context=deps, durability="sync")
        return again

    again = asyncio.run(go())
    assert again["turns_used"] == 1            # still at turn 1, nothing advanced
    assert again.get("outcome") is None
    assert len(attacker.calls) == 1            # turn 2 was never drafted a second time
    paused = _paused_at(copied, 1)
    assert paused.turn == 2 and paused.message == "<attacker turn 2>"


def test_a_targeted_approve_sends_and_pauses_again_at_the_next_turn(real_store):
    # 014/FR-021: a validated, targeted `Command(resume={interrupt_id: "approve"})` sends the pending turn, then
    # pauses again before the next turn's drafted message - never advancing past the last turn actually sent.
    saver = KestrelCheckpointSaver(real_store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    attacker = StubAttacker()
    deps = _deps(attacker)
    config = thread_config(1)

    async def go():
        await copied.ainvoke(_initial(ask=True), config, context=deps, durability="sync")
        paused = await classify(copied, 1, leased=False)
        final = await copied.ainvoke(Command(resume={paused.interrupt_id: "approve"}), config, context=deps,
                                     durability="sync")
        return final

    final = asyncio.run(go())
    assert final["turns_used"] == 2            # turn 2 was sent and recorded
    assert final.get("outcome") is None        # and the run paused again at turn 3
    assert len(attacker.calls) == 2            # turn 2 (already) + turn 3
    paused = _paused_at(copied, 1)
    assert paused.turn == 3


def test_run_to_end_flips_the_flag_off_and_runs_unattended_to_the_end(real_store):
    # 014/FR-022: "Run to end" sends the pending turn and continues unattended, never pausing again for the
    # remainder of the run - the flag is flipped off in the state, and every later approve step is a no-op.
    saver = KestrelCheckpointSaver(real_store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    attacker = StubAttacker()
    deps = _deps(attacker)
    config = thread_config(1)

    async def go():
        await copied.ainvoke(_initial(ask=True), config, context=deps, durability="sync")
        paused = await classify(copied, 1, leased=False)
        return await copied.ainvoke(Command(resume={paused.interrupt_id: "run_to_end"}), config, context=deps,
                                    durability="sync")

    final = asyncio.run(go())
    assert final["outcome"] is not None
    assert final["outcome"].stopping_condition == "turn_cap"   # ran to its natural stop, never a pause
    assert final["turns_used"] == 4
    assert len(attacker.calls) == 3            # turns 2..4 drafted, none held back


def test_the_node_reads_the_state_flag_with_a_default_never_the_deps_flag(real_store):
    # 014/FR-048, research D5, D23: the approve node reads `state.get("ask_before_each_turn", False)` - never a
    # bracket subscript, and never `_LiveDeps.ask_before_each_turn`. A state without the key at all (a checkpoint
    # from before this field existed, or an experiment repetition's own initial state) reads as False and never
    # pauses, even when the deps still claim the flag (the column value).
    saver = KestrelCheckpointSaver(real_store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    attacker = StubAttacker()
    deps = _deps(attacker)                     # deps.ask_before_each_turn is True, but the state has no such key

    final = asyncio.run(copied.ainvoke(_initial_state(), thread_config(1), context=deps, durability="sync"))
    assert final["outcome"] is not None        # ran to the turn cap, never paused
    assert final["turns_used"] == 4
    assert len(attacker.calls) == 3


def test_a_completed_attacker_task_routes_to_approve_not_send(real_store):
    # 014/FR-052, research D5, D18: part 2's topology gain - the completed attacker task's own routing write names
    # "approve" (the edge attacker -> approve is conditional), read from the compiled graph's own record, never a
    # hand-written table that would still say "send". `fail_at=3` fails the approve node's own checkpoint commit,
    # leaving the completed attacker task's routing write as the resume point.
    saver = _FailingPutSaver(real_store, 3)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = make_deps(store=StubStore(), sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                     attacker=StubAttacker(), max_turns=2)

    async def go():
        with pytest.raises(RuntimeError):
            await copied.ainvoke(_initial_state(), thread_config(1), context=deps, durability="sync")
        return await classify(copied, 1, leased=False)

    status = asyncio.run(go())
    assert isinstance(status, checkpointing.Resumable)
    assert status.from_step == "approve"
