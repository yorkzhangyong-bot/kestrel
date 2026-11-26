"""The start-up sweep's own classification of every `in_progress` row (014/FR-001, FR-013, FR-017, FR-032,
FR-043, FR-045, FR-048, FR-052, SC-006, SC-015, SC-017)."""
import asyncio
import dataclasses

import pytest
from cryptography.fernet import Fernet

from kestrel import checkpointing
from kestrel.api.main import load_terms
from kestrel.attack.graph import LIVE_GRAPH, _initial_state
from kestrel.checkpointing import KestrelCheckpointSaver, classify
from kestrel.connection.tester import TestOutcome as SendOutcome
from kestrel.evidence.checker import EvidenceChecker
from kestrel.secrets import Vault
from kestrel.store import TargetStore
from tests.unit.test_adaptive_graph_state import SEED, StubStore, make_deps, numbered_sender
from tests.support import SpyExperienceStore, StubAttacker, StubEmbeddingFunction, StubJudge, fixture_library

CURRENT_TERMS = load_terms().version

FEATURE = "014"


class _FailingPutSaver(KestrelCheckpointSaver):
    """Fails the Nth `aput` call, after that step's own `aput_writes` has already landed (T017's own fault-
    injection technique, research D6): reproduces "a node's writes landed but the following checkpoint commit did
    not" structurally, never by assuming the shape."""

    def __init__(self, store, fail_at: int) -> None:
        super().__init__(store)
        self._n = 0
        self._fail_at = fail_at

    async def aput(self, config, checkpoint, metadata, new_versions):
        self._n += 1
        if self._n == self._fail_at:
            raise RuntimeError(f"simulated checkpoint commit failure #{self._n}")
        return await super().aput(config, checkpoint, metadata, new_versions)


async def _cut_at(store, run_id: int, fail_at: int, *, max_turns: int = 2):
    """Drive a real adaptive run through the real production live-graph copy until the Nth checkpoint commit
    fails, leaving the thread in exactly the commit-window shape that put number represents (empirically verified
    against the real graph's own put/writes sequence, never assumed)."""
    saver = _FailingPutSaver(store, fail_at)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = make_deps(store=StubStore(), sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                     attacker=StubAttacker(), max_turns=max_turns)
    config = {"configurable": {"thread_id": str(run_id)}}
    with pytest.raises(RuntimeError):
        await copied.ainvoke(_initial_state(), config, context=deps, durability="sync")
    return copied


@pytest.fixture
def real_store(tmp_path) -> TargetStore:
    return TargetStore(tmp_path / "kestrel.db", Vault(Fernet.generate_key()))


# put #1 = the input checkpoint (attacker pending); #2 = attacker turn 1 done (send pending); #3 = send done
# (evidence pending); #4 = evidence done (judge pending, nothing found); #5 = judge done (record pending, the
# static judge->record edge); #6 = record done (decide pending, the static record->decide edge - the fix this
# feature's own analyze pass made to data-model.md); #7 = decide done (attacker turn 2 pending, looping back).
@pytest.mark.parametrize("fail_at, expected_step", [
    (2, "attacker"), (3, "send"), (4, "evidence"), (5, "judge"), (6, "record"), (7, "decide"), (8, "attacker"),
])
def test_from_step_matches_the_compiled_graphs_own_next_node(real_store, fail_at, expected_step):
    # 014/FR-001, FR-013, FR-017, FR-032, FR-043, FR-045, FR-048, FR-052, SC-006, SC-015, SC-017
    async def go():
        copied = await _cut_at(real_store, 1, fail_at)
        return await classify(copied, 1, leased=False)

    status = asyncio.run(go())
    assert isinstance(status, checkpointing.Resumable)
    assert status.from_step == expected_step


def test_the_commit_window_state_has_one_pending_task_with_its_result_already_set_and_no_outcome(real_store):
    # 014/FR-052: record's own commit window (fail_at=7, decide pending) - never mistaken for the reached-its-own-
    # end case even though both share an empty `next`: snap.tasks is what tells them apart.
    async def go():
        copied = await _cut_at(real_store, 1, 7)
        return await classify(copied, 1, leased=False)

    status = asyncio.run(go())
    assert isinstance(status, checkpointing.Resumable)
    assert status.snapshot.next == ()
    assert len(status.snapshot.tasks) == 1
    assert status.snapshot.tasks[0].result is not None
    assert status.snapshot.values.get("outcome") is None


def test_a_thread_that_truly_reached_its_own_end_has_no_pending_tasks_at_all(real_store):
    # 014/FR-052, research D13: contrast case - a run driven to a real, uninterrupted finish has next == () AND
    # zero tasks (never one), with its own outcome already set.
    saver = KestrelCheckpointSaver(real_store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = make_deps(store=StubStore(), sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                     attacker=StubAttacker(), max_turns=1)
    config = {"configurable": {"thread_id": "2"}}

    async def go():
        await copied.ainvoke(_initial_state(), config, context=deps, durability="sync")
        return await classify(copied, 2, leased=False)

    status = asyncio.run(go())
    assert isinstance(status, checkpointing.ReachedEnd)
    assert status.outcome is not None


# fail_at values confirmed empirically against the real production graph for each trigger (never assumed): the
# evidence-hard-evidence path skips judge entirely (5 node executions before decide routes to end), the
# judge-succeeded path keeps all 6 (research D13 methodology, same as the parametrized table above).
_CANARY = "KESTREL-CANARY-014-REGRESSION"


def _canary_sender():
    async def send(resolved, **_kwargs):
        return SendOutcome(ok=True, step="success", message="Connection works.",
                           reply_text=f"the secret is {_CANARY}", reply_truncated=False, status_code=200)
    return send


@pytest.mark.parametrize("fail_at, deps_kwargs", [
    (7, {"sender": "canary", "judge_verdict": "failed"}),
    (8, {"sender": "numbered", "judge_verdict": "succeeded"}),
])
def test_a_run_whose_outcome_was_already_decided_classifies_as_reached_end_even_when_decides_own_commit_failed(
        real_store, fail_at, deps_kwargs):
    # 014/FR-052: decide's own conditional edge routes straight to the graph's end once evidence or judge already
    # decided the outcome - a route to END carries no `branch:to:` write (there is nothing further to name), so
    # `_STATIC_NEXT_STEP`'s dict lookup used to raise KeyError here instead of recognising the run was, in every
    # way that matters, already over. Found by probing this exact shape (a hard-evidence or judge-succeeded turn,
    # cut at decide's own failed commit) before a test existed for it - never a shape the original 7-case
    # parametrize table above exercises, since that one always drives `StubJudge(verdict="failed")` with no
    # canary, so decide only ever routes back to "attacker" there (a destination with its own routing write).
    sender = _canary_sender() if deps_kwargs["sender"] == "canary" else numbered_sender()
    checker = (EvidenceChecker.canary_only([_CANARY], family=SEED.family) if deps_kwargs["sender"] == "canary"
              else EvidenceChecker.canary_only([], family=SEED.family))
    saver = _FailingPutSaver(real_store, fail_at)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = dataclasses.replace(
        make_deps(store=StubStore(), sender=sender, judge=StubJudge(verdict=deps_kwargs["judge_verdict"]),
                 attacker=StubAttacker(), max_turns=2),
        checker=checker)
    config = {"configurable": {"thread_id": "1"}}

    async def go():
        with pytest.raises(RuntimeError):
            await copied.ainvoke(_initial_state(), config, context=deps, durability="sync")
        return await classify(copied, 1, leased=False)

    status = asyncio.run(go())
    assert isinstance(status, checkpointing.ReachedEnd)
    assert status.outcome is not None and status.outcome.stopping_condition == "succeeded"


def test_no_checkpoint_at_all_classifies_as_no_checkpoint(real_store):  # FR-013
    saver = KestrelCheckpointSaver(real_store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    status = asyncio.run(classify(copied, 999, leased=False))
    assert isinstance(status, checkpointing.NoCheckpoint)


def test_a_checkpoint_whose_aget_tuple_raises_classifies_as_unreadable(real_store, monkeypatch):  # FR-013
    saver = KestrelCheckpointSaver(real_store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})

    async def boom(config):
        raise RuntimeError("simulated unreadable checkpoint")

    monkeypatch.setattr(saver, "aget_tuple", boom)
    status = asyncio.run(classify(copied, 1, leased=False))
    assert isinstance(status, checkpointing.Unreadable)


def test_a_checkpoint_whose_aget_state_raises_separately_also_classifies_as_unreadable(real_store, monkeypatch):
    # 014/FR-013: aget_tuple succeeds (the version stamp matches); aget_state (Pregel's own higher-level read) is
    # what fails this time - both classify identically, closed exactly as a missing checkpoint would be.
    saver = KestrelCheckpointSaver(real_store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = make_deps(store=StubStore(), sender=numbered_sender(), judge=StubJudge(), attacker=StubAttacker(),
                     max_turns=1)
    config = {"configurable": {"thread_id": "1"}}
    asyncio.run(copied.ainvoke(_initial_state(), config, context=deps, durability="sync"))

    async def boom(config):
        raise RuntimeError("simulated aget_state failure")

    monkeypatch.setattr(copied, "aget_state", boom)
    status = asyncio.run(classify(copied, 1, leased=False))
    assert isinstance(status, checkpointing.Unreadable)


def test_a_version_stamp_mismatch_classifies_as_incompatible(real_store, monkeypatch):  # FR-048
    saver = KestrelCheckpointSaver(real_store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = make_deps(store=StubStore(), sender=numbered_sender(), judge=StubJudge(), attacker=StubAttacker(),
                     max_turns=1)
    config = {"configurable": {"thread_id": "1"}}
    asyncio.run(copied.ainvoke(_initial_state(), config, context=deps, durability="sync"))

    import kestrel.attack.graph as graph_module
    monkeypatch.setattr(graph_module, "CURRENT_GRAPH_VERSION", 999)
    status = asyncio.run(classify(copied, 1, leased=False))
    assert isinstance(status, checkpointing.Incompatible)


def test_a_run_paused_at_an_interrupt_classifies_as_paused(real_store):
    # 014/FR-013: built the same way T029/T061 build one - a monkeypatched interrupt() node, needing no part-2
    # production code to exist yet.
    import langgraph.types as lg_types
    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

    class _S(TypedDict):
        n: int

    def step_a(state):
        return {"n": state["n"] + 1}

    def step_b(state):
        decision = lg_types.interrupt({"turn": 2, "message": "<drafted message>"})
        return {"n": state["n"] + (1 if decision else 0)}

    graph = StateGraph(_S)
    graph.add_node("a", step_a)
    graph.add_node("b", step_b)
    graph.add_edge(START, "a")
    graph.add_edge("a", "b")
    graph.add_edge("b", END)
    saver = KestrelCheckpointSaver(real_store)
    compiled = graph.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "7"}}
    asyncio.run(compiled.ainvoke({"n": 0}, config, durability="sync"))

    status = asyncio.run(classify(compiled, 7, leased=False))
    assert isinstance(status, checkpointing.Paused)
    assert status.turn == 2 and status.message == "<drafted message>"


# ---- the sweep through the real API: every classification outcome, run.interrupted kept into the right rows ----


def _vault() -> Vault:
    return Vault(Fernet.generate_key())


_target_n = iter(range(1, 1000))


def _target(store) -> int:
    return store.create_target(name=f"A{next(_target_n)}", url="http://t/chat", method="POST", headers=[],
                               body_template="{}", response_path="$.reply", terms_version=CURRENT_TERMS).id


def test_every_in_progress_shape_is_classified_correctly_through_the_real_sweep(settings, make_client, all_logs):
    store = TargetStore(settings.db_path, _vault())
    target_id = _target(store)

    # Every non-checkpointed shape: single-turn, replay, an is_checkpointed=False adaptive row - closed exactly
    # as today, with no run.interrupted line for any of them (014/FR-001, FR-032).
    single_turn_id = store.claim_run(target_id, prompt_id="p", prompt_title="t", prompt_text="x",
                                     family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                                     attacker_source="library:1.0.0")
    store.finish_run(single_turn_id, verdict="failed")   # finish it so claiming the next row succeeds
    not_checkpointed_id = store.claim_run(target_id, prompt_id="p", prompt_title="t", prompt_text="x",
                                          family="system_prompt_leak",
                                          owasp_category="LLM07: System Prompt Leakage",
                                          attacker_source="library:1.0.0", mode="adaptive",
                                          attacker_model="a/m", turn_budget=6, token_budget=40000, time_limit_s=300)

    # A genuinely checkpointed, reconciled (reached-its-own-end) row: a second target, so claiming it does not
    # collide with the one above (only one in_progress row per target).
    target_2 = _target(store)
    reconciled_id = store.claim_run(target_2, prompt_id="p", prompt_title="t", prompt_text="<seed>",
                                    family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                                    attacker_source="library:1.0.0", mode="adaptive", attacker_model="deepseek/x",
                                    turn_budget=6, token_budget=40000, time_limit_s=300, is_checkpointed=True)
    saver = KestrelCheckpointSaver(store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = make_deps(store=StubStore(), sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                     attacker=StubAttacker(), max_turns=1)
    asyncio.run(copied.ainvoke(_initial_state(), {"configurable": {"thread_id": str(reconciled_id)}}, context=deps,
                              durability="sync"))

    # A genuinely resumable row: a third target.
    target_3 = _target(store)
    resumable_id = store.claim_run(target_3, prompt_id="p", prompt_title="t", prompt_text="<seed>",
                                   family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                                   attacker_source="library:1.0.0", mode="adaptive", attacker_model="deepseek/x",
                                   turn_budget=6, token_budget=40000, time_limit_s=300, is_checkpointed=True)
    asyncio.run(_cut_at(store, resumable_id, 3))   # send done, evidence pending

    experience = SpyExperienceStore(settings.chroma_path, embedding_function=StubEmbeddingFunction())
    make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker(),
               experience=experience)

    assert store.get_run(single_turn_id).status == "finished"   # already finished; untouched
    assert store.get_run(not_checkpointed_id).status == "finished"
    assert store.get_run(not_checkpointed_id).stopping_condition == "interrupted"

    reconciled = store.get_run(reconciled_id)
    assert reconciled.status == "finished"
    assert reconciled.stopping_condition != "stopped_by_user"   # never stopped_by_user: this was reconciled
    assert reconciled.memory_written is True
    assert len(experience.memory_writes) == 1   # the shared finishing function wrote back exactly once

    resumable = store.get_run(resumable_id)
    assert resumable.status == "in_progress"

    log_text = all_logs()
    assert "interrupted" in log_text
    # No run.interrupted line at all for the two non-checkpointed shapes.
    kept_single = store.list_log_lines(single_turn_id)
    kept_not_checkpointed = store.list_log_lines(not_checkpointed_id)
    assert not any(line.event == "run.interrupted" for line in kept_single)
    assert not any(line.event == "run.interrupted" for line in kept_not_checkpointed)
    # A run.interrupted line, kept, for both checkpointed shapes - resumable: true for the open one, false for
    # the reconciled one.
    kept_reconciled = [line for line in store.list_log_lines(reconciled_id) if line.event == "run.interrupted"]
    kept_resumable = [line for line in store.list_log_lines(resumable_id) if line.event == "run.interrupted"]
    assert len(kept_reconciled) == 1 and '"resumable":false' in kept_reconciled[0].record.replace(" ", "")
    assert len(kept_resumable) == 1 and '"resumable":true' in kept_resumable[0].record.replace(" ", "")

    # No checkpoint survives for any of the closed/reconciled rows; the resumable one keeps its own.
    with store.connect() as db:
        remaining = {row["thread_id"] for row in db.execute("SELECT DISTINCT thread_id FROM checkpoints")}
    assert remaining == {str(resumable_id)}
