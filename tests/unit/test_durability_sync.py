"""Every invocation of a checkpointed live graph requests synchronous durability (014/FR-003, SC-012, research
D3): the step just run is durably committed before the next one starts - the only mode under which a crash can
never leave the persisted progress more than one in-flight step behind what already happened. Durability is never
passed to a checkpointer-free call (the experiment harness's own call site)."""
import ast
import asyncio
import inspect

import pytest
from cryptography.fernet import Fernet
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from kestrel.checkpointing import KestrelCheckpointSaver
from kestrel.secrets import Vault
from kestrel.store import TargetStore

FEATURE = "014"


class _S(TypedDict):
    n: int


@pytest.fixture
def store(tmp_path) -> TargetStore:
    return TargetStore(tmp_path / "kestrel.db", Vault(Fernet.generate_key()))


def _slow_graph(log: list, delay_s: float, store: TargetStore):
    """A three-node linear graph whose own nodes are instantaneous, but whose checkpoint commit sleeps `delay_s`
    before actually writing - a deliberately slow checkpoint write (SC-012)."""

    class SlowSaver(KestrelCheckpointSaver):
        async def aput(self, config, checkpoint, metadata, new_versions):
            await asyncio.sleep(delay_s)
            log.append(("committed", checkpoint["channel_values"].get("n")))
            return await super().aput(config, checkpoint, metadata, new_versions)

    def node(name: str):
        def body(state: _S) -> _S:
            log.append(("started", name, state["n"]))
            return {"n": state["n"] + 1}
        return body

    graph = StateGraph(_S)
    for name in ("a", "b", "c"):
        graph.add_node(name, node(name))
    graph.add_edge(START, "a")
    graph.add_edge("a", "b")
    graph.add_edge("b", "c")
    graph.add_edge("c", END)
    return graph.compile(checkpointer=SlowSaver(store))


async def _invoke(graph, thread_id: str, *, durability: str | None = None):
    config = {"configurable": {"thread_id": thread_id}}
    kwargs = {"durability": durability} if durability else {}
    return await graph.ainvoke({"n": 0}, config, **kwargs)


def _max_consecutive_starts(log: list) -> int:
    """The longest run of "started" entries with no "committed" between them - 1 under synchronous durability
    (every step's own commit lands before the next node starts), more than 1 under the library's own default."""
    longest = current = 0
    for entry in log:
        if entry[0] == "started":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def test_synchronous_durability_commits_each_step_before_the_next_one_starts(store):  # FR-003, SC-012
    log: list = []
    graph = _slow_graph(log, delay_s=0.05, store=store)
    asyncio.run(_invoke(graph, "sync-thread", durability="sync"))
    assert [e for e in log if e[0] == "started"] == [("started", "a", 0), ("started", "b", 1), ("started", "c", 2)]
    assert _max_consecutive_starts(log) == 1


def test_the_librarys_default_durability_lets_several_steps_start_before_any_checkpoint_commits(store):
    # 014/research D3: contrast case, same graph and the same slow saver, the library's own default (no
    # durability kwarg at all) - several nodes' own "started" entries land before the matching "committed".
    log: list = []
    graph = _slow_graph(log, delay_s=0.05, store=store)
    asyncio.run(_invoke(graph, "default-thread"))
    assert _max_consecutive_starts(log) >= 2


def test_durability_is_never_passed_to_the_experiment_harnesss_bare_checkpointer_free_call():  # FR-003, research D3
    """Source inspection, not a runtime assertion: passing `durability=` against a checkpointer-free graph only
    ever surfaces as a library warning, never a raised error, so the experiment harness's own call site - which
    never passes `graph=`/`app_state=` to `run_adaptive` and so always runs the bare LIVE_GRAPH - must simply
    never name the keyword at all."""
    from kestrel.experiments import engine

    tree = ast.parse(inspect.getsource(engine))
    offenders = [node.lineno for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and any(keyword.arg == "durability" for keyword in getattr(node, "keywords", ()))]
    assert offenders == []
