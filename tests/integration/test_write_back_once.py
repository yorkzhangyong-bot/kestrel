"""Write-back happens exactly once per finished run, whichever path finishes it, and `finish_run` itself is never
called twice for the same row (014/FR-043, FR-055, SC-015). A run left in progress (cut mid-step, never resumed or
stopped) writes back zero times at that point."""
import asyncio

import httpx
import pytest

from kestrel.store import TargetStore
from tests.integration.test_stop_endpoint import _claim_checkpointed, _cut_at, _target
from tests.support import (SpyExperienceStore, StubAttacker, StubEmbeddingFunction, StubJudge, fixture_library,
                           model_settings, real_attacker, real_judge)

FEATURE = "014"


def test_a_run_resumed_to_a_normal_finish_writes_back_exactly_once(settings, make_client, model_transport):
    settings = model_settings(settings)
    experience = SpyExperienceStore(settings.chroma_path, embedding_function=StubEmbeddingFunction())
    api = make_client(settings, transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), attacker=real_attacker(model_transport),
                      experience=experience)
    store = api.app.state.store
    target_id = _target(store)
    run_id = _claim_checkpointed(store, target_id)
    asyncio.run(_cut_at(store, run_id, 4, judge=StubJudge(verdict="failed")))   # merely resumable

    response = api.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 200 and response.json()["status"] == "finished"
    assert len(experience.memory_writes) == 1


def test_a_run_stopped_the_ordinary_case_writes_back_exactly_once(settings, make_client):
    experience = SpyExperienceStore(settings.chroma_path, embedding_function=StubEmbeddingFunction())
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker(),
                      experience=experience)
    store = api.app.state.store
    target_id = _target(store)
    run_id = _claim_checkpointed(store, target_id)
    asyncio.run(_cut_at(store, run_id, 4, judge=StubJudge(verdict="failed")))

    response = api.post(f"/api/runs/{run_id}/stop")
    assert response.status_code == 200
    assert len(experience.memory_writes) == 1


def test_a_run_stop_reconciles_from_its_own_already_decided_outcome_writes_back_exactly_once(settings, make_client):
    experience = SpyExperienceStore(settings.chroma_path, embedding_function=StubEmbeddingFunction())
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker(),
                      experience=experience)
    store = api.app.state.store
    target_id = _target(store)
    run_id = _claim_checkpointed(store, target_id)
    asyncio.run(_cut_at(store, run_id, 7, judge=StubJudge(verdict="succeeded")))   # the commit-window reconciliation

    response = api.post(f"/api/runs/{run_id}/stop")
    assert response.status_code == 200
    assert len(experience.memory_writes) == 1


def test_a_run_cut_off_mid_step_and_left_resumable_writes_back_zero_times(settings, make_client):
    experience = SpyExperienceStore(settings.chroma_path, embedding_function=StubEmbeddingFunction())
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker(),
                      experience=experience)
    store = api.app.state.store
    target_id = _target(store)
    run_id = _claim_checkpointed(store, target_id)
    asyncio.run(_cut_at(store, run_id, 4, judge=StubJudge(verdict="failed")))

    assert experience.memory_writes == []
    before = api.get(f"/api/runs/{run_id}").json()
    assert before["status"] == "in_progress" and experience.memory_writes == []


def _counting_finish_run(monkeypatch, calls: list[int]):
    original = TargetStore.finish_run

    def counted(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(TargetStore, "finish_run", counted)


def test_finish_run_is_called_exactly_once_per_finished_run(settings, make_client, model_transport, monkeypatch):
    # FR-055: the API-path finishing function (finish_api_run) must never re-finish a row run_adaptive, stop_run
    # or finish_with_outcome already finished for it - it only writes back and deletes the checkpoint.
    calls: list[int] = []
    _counting_finish_run(monkeypatch, calls)
    model_backed_settings = model_settings(settings)
    api = make_client(model_backed_settings, transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), attacker=real_attacker(model_transport))
    store = api.app.state.store
    target_id = _target(store)
    run_id = _claim_checkpointed(store, target_id)
    asyncio.run(_cut_at(store, run_id, 4, judge=StubJudge(verdict="failed")))

    assert api.post(f"/api/runs/{run_id}/resume").status_code == 200
    assert len(calls) == 1

    target_id_2 = _target(store, "B")
    run_id_2 = _claim_checkpointed(store, target_id_2)
    asyncio.run(_cut_at(store, run_id_2, 4, judge=StubJudge(verdict="failed")))
    calls.clear()
    assert api.post(f"/api/runs/{run_id_2}/stop").status_code == 200
    assert len(calls) == 1

    target_id_3 = _target(store, "C")
    run_id_3 = _claim_checkpointed(store, target_id_3)
    asyncio.run(_cut_at(store, run_id_3, 7, judge=StubJudge(verdict="succeeded")))
    calls.clear()
    assert api.post(f"/api/runs/{run_id_3}/stop").status_code == 200
    assert len(calls) == 1


def test_a_start_that_raises_still_releases_its_lease(settings, make_client, monkeypatch):
    # FR-055: an uncaught exception from inside a node must still release the run's lease via the lease()
    # context manager's own __exit__ - never leaving a crashed original start stuck as permanently "executing".
    # A graph node function reference is baked into the compiled graph at import time (add_node captures the
    # object, not a live module lookup), so patching kestrel.attack.graph's own module attribute would not reach
    # it; EvidenceChecker.check_turn is looked up on the class at call time (instance.check_turn()), so patching
    # the class does.
    from kestrel.evidence.checker import EvidenceChecker

    async def boom(self, turn, reply, remaining):
        raise RuntimeError("simulated node crash")

    monkeypatch.setattr(EvidenceChecker, "check_turn", boom)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"reply": "<agent reply>"}))
    api = make_client(settings, transport=transport, library=fixture_library(), judge=StubJudge(),
                      attacker=StubAttacker())
    target = _target(api.app.state.store)

    with pytest.raises(RuntimeError, match="simulated node crash"):
        api.post("/api/runs", json={"target_id": target, "family": "system_prompt_leak", "mode": "adaptive"})

    assert api.app.state.leases == set()
    run_id = api.app.state.store.list_runs(target)[0].id
    response = api.post(f"/api/runs/{run_id}/stop")
    assert response.status_code != 409 or response.json()["error"]["code"] != "run_executing"
