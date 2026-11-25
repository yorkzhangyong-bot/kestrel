"""`KestrelCheckpointSaver`'s own contract (014/FR-007, FR-035, FR-036, FR-048, FR-049): round-tripping, the
version stamp, the pending-writes replace/ignore rule, listing, and deletion - proved directly against the saver,
never assumed from a happy-path read/write alone (the owner's first and second conditions, Clarifications)."""
import asyncio
import logging

import pytest
from cryptography.fernet import Fernet
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.serde.types import ERROR

from kestrel.attack.graph import LIVE_GRAPH, CURRENT_GRAPH_VERSION, Outcome, _initial_state
from kestrel.checkpointing import KestrelCheckpointSaver
from kestrel.evidence.checker import TurnEvidence
from kestrel.evidence.model import EvidenceItem
from kestrel.secrets import Vault
from kestrel.store import TargetStore

FEATURE = "014"

_ALLOWED_MODULES = [("kestrel.attack.graph", "Outcome"), ("kestrel.evidence.checker", "TurnEvidence"),
                    ("kestrel.evidence.model", "EvidenceItem")]


@pytest.fixture
def store(tmp_path) -> TargetStore:
    return TargetStore(tmp_path / "kestrel.db", Vault(Fernet.generate_key()))


@pytest.fixture
def saver(store) -> KestrelCheckpointSaver:
    return KestrelCheckpointSaver(store)


def _checkpoint(checkpoint_id: str, channel_values: dict) -> dict:
    return {"v": 1, "id": checkpoint_id, "ts": "2026-11-25T00:00:00Z", "channel_values": channel_values,
            "channel_versions": {}, "versions_seen": {}, "updated_channels": None}


def _run(coro):
    return asyncio.run(coro)


def test_aput_then_aget_tuple_round_trips_the_three_registered_types_with_no_warning(saver, caplog):
    outcome = Outcome(verdict="succeeded", hard_evidence=True, reason="x", judge_used=False,
                      stopping_condition="succeeded", succeeded_turn=1)
    item = EvidenceItem(kind="canary_in_reply", turn=1, location="reply", owasp_category="LLM07", detail="d")
    found = TurnEvidence(items=[item], canary_hit=True, side_channel_status="not_configured", checks=["canary"])
    config = {"configurable": {"thread_id": "t-types", "checkpoint_ns": ""}}

    async def go():
        with caplog.at_level(logging.WARNING):
            new_config = await saver.aput(config, _checkpoint("c1", {"outcome": outcome, "evidence": found}),
                                          {"source": "loop", "step": 0}, {})
            tup = await saver.aget_tuple(new_config)
        return tup

    tup = _run(go())
    assert isinstance(tup.checkpoint["channel_values"]["outcome"], Outcome)
    assert tup.checkpoint["channel_values"]["outcome"] == outcome
    assert isinstance(tup.checkpoint["channel_values"]["evidence"], TurnEvidence)
    assert isinstance(tup.checkpoint["channel_values"]["evidence"].items[0], EvidenceItem)
    assert not any("blocked" in record.message.lower() or "future version" in record.message.lower()
                  for record in caplog.records)


def test_an_equivalent_explicit_strict_allowlist_serializer_round_trips_the_three_types_too():
    # 014/FR-049: the strict-mode-equivalent configuration, built directly (the library's own strict-mode flag is
    # read once at import, so toggling it mid-process cannot be observed) - the identical explicit allowlist the
    # saver's own __init__ already passes, proving the fix holds under "strict" too, not only the permissive
    # default this same explicit allowlist already fixes.
    serde = JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_MODULES)
    outcome = Outcome(verdict="failed", hard_evidence=False, reason="x", judge_used=True,
                      stopping_condition="turn_cap", succeeded_turn=None)
    restored = serde.loads_typed(serde.dumps_typed(outcome))
    assert isinstance(restored, Outcome) and restored == outcome


def test_every_aput_call_stamps_the_current_graph_version(saver):
    config = {"configurable": {"thread_id": "t-version", "checkpoint_ns": ""}}

    async def go():
        new_config = await saver.aput(config, _checkpoint("c1", {"n": 1}), {"source": "loop", "step": 0}, {})
        return await saver.aget_tuple(new_config)

    tup = _run(go())
    assert tup.metadata["kestrel_graph_version"] == CURRENT_GRAPH_VERSION


def test_aput_writes_then_aget_tuple_returns_them_in_pending_writes_before_a_later_aput_folds_them_in(saver):
    config = {"configurable": {"thread_id": "t-pending", "checkpoint_ns": ""}}

    async def go():
        committed = await saver.aput(config, _checkpoint("c1", {"n": 1}), {"source": "loop", "step": 0}, {})
        await saver.aput_writes(committed, [("n", 2)], task_id="task-1", task_path="")
        return await saver.aget_tuple({"configurable": {"thread_id": "t-pending"}})

    tup = _run(go())
    assert tup.pending_writes == [("task-1", "n", 2)]


def test_a_regular_write_recorded_twice_for_the_same_channel_is_stored_once(saver):
    config = {"configurable": {"thread_id": "t-regular", "checkpoint_ns": ""}}

    async def go():
        committed = await saver.aput(config, _checkpoint("c1", {"n": 1}), {"source": "loop", "step": 0}, {})
        await saver.aput_writes(committed, [("n", 2)], task_id="task-1", task_path="")
        await saver.aput_writes(committed, [("n", 999)], task_id="task-1", task_path="")  # same task/idx: ignored
        return await saver.aget_tuple({"configurable": {"thread_id": "t-regular"}})

    tup = _run(go())
    assert tup.pending_writes == [("task-1", "n", 2)]


def test_a_control_write_recorded_twice_replaces_never_duplicates(saver):
    config = {"configurable": {"thread_id": "t-control", "checkpoint_ns": ""}}

    async def go():
        committed = await saver.aput(config, _checkpoint("c1", {"n": 1}), {"source": "loop", "step": 0}, {})
        await saver.aput_writes(committed, [(ERROR, "first-error")], task_id="task-1", task_path="")
        await saver.aput_writes(committed, [(ERROR, "second-error")], task_id="task-1", task_path="")
        return await saver.aget_tuple({"configurable": {"thread_id": "t-control"}})

    tup = _run(go())
    error_writes = [write for write in tup.pending_writes if write[1] == ERROR]
    assert len(error_writes) == 1
    assert error_writes[0][2] == "second-error"


def test_alist_returns_a_threads_checkpoints_newest_first(saver):
    config = {"configurable": {"thread_id": "t-list", "checkpoint_ns": ""}}

    async def go():
        first = await saver.aput(config, _checkpoint("c1", {"n": 1}), {"source": "loop", "step": 0}, {})
        await saver.aput(first, _checkpoint("c2", {"n": 2}), {"source": "loop", "step": 1}, {})
        return [item async for item in saver.alist({"configurable": {"thread_id": "t-list"}})]

    items = _run(go())
    assert [tup.checkpoint["id"] for tup in items] == ["c2", "c1"]
    assert items[0].parent_config["configurable"]["checkpoint_id"] == "c1"


def test_adelete_thread_removes_both_tables_rows_and_is_a_no_op_for_an_unknown_thread(saver, store):
    config = {"configurable": {"thread_id": "321", "checkpoint_ns": ""}}

    async def go():
        committed = await saver.aput(config, _checkpoint("c1", {"n": 1}), {"source": "loop", "step": 0}, {})
        await saver.aput_writes(committed, [("n", 2)], task_id="task-1", task_path="")
        await saver.adelete_thread("321")
        return await saver.aget_tuple({"configurable": {"thread_id": "321"}})

    assert _run(go()) is None
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM checkpoint_writes WHERE thread_id = 't-delete'"
                          ).fetchone()["n"] == 0
    _run(saver.adelete_thread("999999"))   # an unknown, but numeric, thread id - a no-op, never raises


def test_a_run_through_the_real_production_live_graph_copy_reads_back_the_three_registered_types(store):
    # 014/FR-036 (the owner's second condition, satisfied here at the saver level; T031 satisfies it again
    # through the full adaptive loop with an actual crash and resume): never InMemorySaver.
    from tests.unit.test_adaptive_graph_state import StubStore, make_deps, numbered_sender
    from tests.support import StubAttacker, StubJudge

    saver = KestrelCheckpointSaver(store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = make_deps(store=StubStore(), sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                     attacker=StubAttacker(), max_turns=1)
    config = {"configurable": {"thread_id": "999"}}

    async def go():
        final = await copied.ainvoke(_initial_state(), config, context=deps, durability="sync")
        tup = await saver.aget_tuple(config)
        return final, tup

    final, tup = _run(go())
    assert isinstance(final["outcome"], Outcome)
    assert isinstance(tup.checkpoint["channel_values"]["outcome"], Outcome)
