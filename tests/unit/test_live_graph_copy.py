"""Each app builds its own checkpointed copy of `LIVE_GRAPH`; the module-level graph itself is never mutated
(014/FR-001, research D2)."""
import asyncio

import pytest
from cryptography.fernet import Fernet

from kestrel.attack.graph import LIVE_GRAPH, _initial_state
from kestrel.checkpointing import KestrelCheckpointSaver
from kestrel.secrets import Vault
from kestrel.store import TargetStore

FEATURE = "014"


@pytest.fixture
def saver(tmp_path) -> KestrelCheckpointSaver:
    return KestrelCheckpointSaver(TargetStore(tmp_path / "kestrel.db", Vault(Fernet.generate_key())))


def test_copy_produces_a_checkpointed_object_bound_to_the_given_saver(saver):  # FR-001, research D2
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    assert copied.checkpointer is saver
    assert LIVE_GRAPH.checkpointer is None   # never mutated


def test_the_copy_has_the_same_node_set_as_the_module_level_graph(saver):  # FR-001, research D2
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    assert set(copied.nodes) == set(LIVE_GRAPH.nodes)


def test_the_bare_module_level_graph_still_runs_with_no_thread_id_at_all(saver):  # FR-001, research D2
    # Proves the module-level graph is never mutated into requiring a thread_id: building a checkpointed copy
    # (above) must leave LIVE_GRAPH itself exactly as usable as it always was, with an empty config.
    _ = LIVE_GRAPH.copy(update={"checkpointer": saver})

    async def go():
        from tests.unit.test_adaptive_graph_state import StubStore, make_deps, numbered_sender
        from tests.support import StubAttacker, StubJudge
        deps = make_deps(store=StubStore(), sender=numbered_sender(), judge=StubJudge(), attacker=StubAttacker(),
                         max_turns=1)
        return await LIVE_GRAPH.ainvoke(_initial_state(), {}, context=deps)

    final = asyncio.run(go())
    assert final["outcome"].stopping_condition == "turn_cap"


def test_two_independent_apps_each_get_their_own_copy_bound_to_their_own_store(tmp_path, make_client):
    # 014/FR-001, research D2: nothing from one app's own checkpointed copy leaks into the other's.
    settings_a = _settings(tmp_path / "a")
    settings_b = _settings(tmp_path / "b")
    api_a = make_client(settings_a)
    api_b = make_client(settings_b)
    graph_a = api_a.app.state.live_graph
    graph_b = api_b.app.state.live_graph
    assert graph_a is not graph_b
    assert graph_a.checkpointer is not graph_b.checkpointer
    assert graph_a.checkpointer._store is not graph_b.checkpointer._store
    assert LIVE_GRAPH.checkpointer is None


def _settings(db_dir):
    from kestrel.settings import Settings
    return Settings(mode="local", db_path=db_dir / "data" / "kestrel.db", key_file=db_dir / "keys" / "secret.key",
                    secret_key=None, chroma_path=db_dir / "data" / "chroma")
