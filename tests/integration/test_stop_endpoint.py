"""`POST /api/runs/{id}/stop`: the documented way out of any resumable run, paused or not, without ever resuming
its graph (014/FR-025, FR-040, FR-047, FR-051, FR-054, FR-056, SC-014, research D7, D11).

Every row this file seeds is built *after* `make_client(...)` has already returned (through the running app's own
`app.state.store`/`app.state.live_graph`) - never before it - so the one-time start-up sweep never gets a chance
to touch it first; the sweep's own behaviour on these identical shapes is `test_start_up_sweep_classification.py`'s
own job, not this file's. Every `fail_at` value below was confirmed empirically against the real production graph,
driven with the real store as `deps.store` so a node's own SQL side effect (never gated by the checkpoint commit
that follows it) lands in the same database this file later inspects - never assumed from the put-numbering
comment in `test_start_up_sweep_classification.py` alone, which uses a disconnected `StubStore` for a different
purpose (research D6, D13)."""
import asyncio
import dataclasses

import pytest

from kestrel.api.main import INTERRUPTED_REASON, load_terms
from kestrel.attack.graph import LIVE_GRAPH, _initial_state
from kestrel.checkpointing import KestrelCheckpointSaver, lease
from kestrel.connection.tester import TestOutcome as SendOutcome
from kestrel.evidence.checker import EvidenceChecker
from kestrel.runs import stop_run
from tests.support import SpyExperienceStore, StubAttacker, StubEmbeddingFunction, StubJudge, fixture_library
from tests.unit.test_adaptive_graph_state import SEED, StubStore, make_deps, numbered_sender
from tests.unit.test_start_up_sweep_classification import _FailingPutSaver

FEATURE = "014"

CURRENT_TERMS = load_terms().version
BODY_TEMPLATE = '{"message": "{{prompt}}"}'
CANARY = "KESTREL-CANARY-014-STOP-TEST"


def _target(store, name="A") -> int:
    return store.create_target(name=name, url="http://t/chat", method="POST", headers=[],
                               body_template=BODY_TEMPLATE, response_path="$.reply",
                               terms_version=CURRENT_TERMS).id


def _claim_checkpointed(store, target_id, *, mode="adaptive", is_checkpointed=True) -> int:
    return store.claim_run(target_id, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>",
                           family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                           attacker_source="library:1.0.0", mode=mode, attacker_model="deepseek/x",
                           turn_budget=6, token_budget=40000, time_limit_s=300, is_checkpointed=is_checkpointed,
                           judge_model="google/gemini-3.8-flash", judge_prompt_id="judge", judge_prompt_version="1")


def _canary_sender():
    async def send(resolved, **_kwargs):
        return SendOutcome(ok=True, step="success", message="Connection works.",
                           reply_text=f"the secret is {CANARY}", reply_truncated=False, status_code=200)
    return send


async def _cut_at(store, run_id, fail_at, *, judge, sender=None, canary=False, max_turns=2):
    """Drives the real production live-graph copy, backed by `store` for *both* the checkpointer and the graph's
    own `deps.store` (so `record`'s own `add_turn_with_evidence` call is a real write into the same database this
    file later inspects), until the Nth checkpoint commit fails.

    `make_deps` (shared with `test_adaptive_graph_state.py`, written for single-run-id-1 tests) hardcodes
    `run_id=1`; `dataclasses.replace` corrects it to this call's own `run_id`, or `record`'s own SQL write lands
    under run id 1 regardless of which thread the graph itself was driven under - confirmed empirically (a
    standalone two-run script) before this line existed, the same way the fail_at values themselves were."""
    saver = _FailingPutSaver(store, fail_at)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = dataclasses.replace(
        make_deps(store=store, sender=sender or numbered_sender(), judge=judge, attacker=StubAttacker(),
                 max_turns=max_turns),
        run_id=run_id)
    if canary:
        deps = dataclasses.replace(deps, checker=EvidenceChecker.canary_only([CANARY], family=SEED.family))
    config = {"configurable": {"thread_id": str(run_id)}}
    with pytest.raises(RuntimeError):
        await copied.ainvoke(_initial_state(), config, context=deps, durability="sync")


def test_stop_on_a_merely_resumable_run_finishes_without_running_the_graph_again(settings, make_client):
    attacker, judge = StubAttacker(), StubJudge()
    experience = SpyExperienceStore(settings.chroma_path, embedding_function=StubEmbeddingFunction())
    api = make_client(settings, library=fixture_library(), judge=judge, attacker=attacker, experience=experience)
    store = api.app.state.store
    target_id = _target(store)
    run_id = _claim_checkpointed(store, target_id)
    store.add_turn(run_id, position=1, attacker_message="<m1>", reply_text="<r1>", judge_verdict="failed")
    asyncio.run(_cut_at(store, run_id, 4, judge=StubJudge(verdict="failed")))   # send done, evidence pending

    before = api.get(f"/api/runs/{run_id}").json()
    assert before["run_state"] == "resumable" and before["resumable"] is True

    response = api.post(f"/api/runs/{run_id}/stop")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "finished"
    assert body["stopping_condition"] == "stopped_by_user"
    assert body["verdict"] == "failed"   # the last durably judged run_turns row
    assert body["judge_model"] == "google/gemini-3.8-flash"   # preserved, never null
    assert attacker.calls == [] and judge.calls == []   # the graph never ran again, with the app's own clients
    assert len(experience.memory_writes) == 1

    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM checkpoints WHERE thread_id = ?",
                          (str(run_id),)).fetchone()["n"] == 0

    # The target's lock is released: a new run now succeeds.
    r2 = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak", "mode": "single_turn"})
    assert r2.status_code == 201


def test_stop_reconciles_a_reached_its_own_end_run_never_stopped_by_user(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store
    target_id = _target(store)
    run_id = _claim_checkpointed(store, target_id)
    saver = KestrelCheckpointSaver(store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = dataclasses.replace(
        make_deps(store=store, sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                 attacker=StubAttacker(), max_turns=1),
        run_id=run_id)
    asyncio.run(copied.ainvoke(_initial_state(), {"configurable": {"thread_id": str(run_id)}}, context=deps,
                              durability="sync"))

    before = api.get(f"/api/runs/{run_id}").json()
    assert before["run_state"] == "stoppable" and before["resumable"] is False

    response = api.post(f"/api/runs/{run_id}/stop")
    assert response.status_code == 200
    body = response.json()
    assert body["stopping_condition"] != "stopped_by_user"
    assert body["stopping_condition"] == "turn_cap"   # the real, already-decided outcome


def test_stop_reconciles_a_commit_window_outcome_and_records_the_pending_turn(settings, make_client):
    # 014/FR-051: the judge half of the commit window - judge already succeeded (fail_at=7, from_step=="record")
    # but record had not yet durably written it (confirmed empirically: 0 run_turns rows before this call).
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store
    target_id = _target(store)
    run_id = _claim_checkpointed(store, target_id)
    asyncio.run(_cut_at(store, run_id, 7, judge=StubJudge(verdict="succeeded")))
    assert store.list_turns(run_id) == []

    before = api.get(f"/api/runs/{run_id}").json()
    assert before["run_state"] == "stoppable" and before["resumable"] is False

    response = api.post(f"/api/runs/{run_id}/stop")
    assert response.status_code == 200
    body = response.json()
    assert body["stopping_condition"] == "succeeded"
    assert body["judge_model"] == "google/gemini-3.8-flash"   # judge_used: preserved, never null
    assert len(body["turns"]) == 1   # the pending turn was recorded, through record's own idempotent call


def test_stop_does_not_write_a_phantom_duplicate_turn(settings, make_client):  # FR-051
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store

    # The evidence half of the commit window (record not yet run): recorded exactly once, never zero, never two.
    target_a = _target(store, "A")
    run_a = _claim_checkpointed(store, target_a)
    asyncio.run(_cut_at(store, run_a, 6, judge=StubJudge(verdict="failed"), sender=_canary_sender(), canary=True))
    assert store.list_turns(run_a) == []
    response_a = api.post(f"/api/runs/{run_a}/stop")
    assert response_a.status_code == 200
    assert len(response_a.json()["turns"]) == 1

    # record's own commit window: record already ran for real (its checkpoint commit is what failed) - Stop's
    # own ELSE branch (no outcome decided: judge failed, decide never ran) must never add a second row on top of
    # the one record itself already, durably wrote.
    target_b = _target(store, "B")
    run_b = _claim_checkpointed(store, target_b)
    asyncio.run(_cut_at(store, run_b, 8, judge=StubJudge(verdict="failed")))
    assert len(store.list_turns(run_b)) == 1
    response_b = api.post(f"/api/runs/{run_b}/stop")
    assert response_b.status_code == 200
    assert len(response_b.json()["turns"]) == 1

    # decide's own commit window (the next turn not yet begun): still never a phantom "turn 2" built from
    # turns_used + 1 off fields decide's own pass-through state left uncleared.
    target_c = _target(store, "C")
    run_c = _claim_checkpointed(store, target_c)
    asyncio.run(_cut_at(store, run_c, 9, judge=StubJudge(verdict="failed")))
    assert len(store.list_turns(run_c)) == 1
    response_c = api.post(f"/api/runs/{run_c}/stop")
    assert response_c.status_code == 200
    assert len(response_c.json()["turns"]) == 1


def test_stop_on_no_checkpoint_or_unreadable_closes_exactly_like_the_sweep_never_a_409(settings, make_client,
                                                                                       monkeypatch):
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    store = api.app.state.store
    target_id = _target(store)
    run_id = _claim_checkpointed(store, target_id)   # claimed, but no checkpoint was ever written for it

    response = api.post(f"/api/runs/{run_id}/stop")
    assert response.status_code == 200
    body = response.json()
    assert body["stopping_condition"] == "interrupted"
    assert body["verdict"] == "unclear"

    # Separately: a checkpoint exists but cannot be read at all.
    target_2 = _target(store, "B")
    run_2 = _claim_checkpointed(store, target_2)
    saver = KestrelCheckpointSaver(store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = dataclasses.replace(
        make_deps(store=store, sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                 attacker=StubAttacker(), max_turns=2),
        run_id=run_2)
    asyncio.run(copied.ainvoke(_initial_state(), {"configurable": {"thread_id": str(run_2)}}, context=deps,
                              durability="sync"))

    async def boom(config):
        raise RuntimeError("simulated unreadable checkpoint")

    monkeypatch.setattr(api.app.state.live_graph.checkpointer, "aget_tuple", boom)
    response_2 = api.post(f"/api/runs/{run_2}/stop")
    assert response_2.status_code == 200
    body_2 = response_2.json()
    assert body_2["stopping_condition"] == "interrupted"
    assert body_2["verdict"] == "unclear"


def test_stops_no_checkpoint_close_matches_the_sweeps_reason_and_skips_write_back(settings, make_client):  # FR-056
    experience = SpyExperienceStore(settings.chroma_path, embedding_function=StubEmbeddingFunction())
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker(),
                      experience=experience)
    store = api.app.state.store
    target_id = _target(store)
    run_id = _claim_checkpointed(store, target_id)
    response = api.post(f"/api/runs/{run_id}/stop")
    assert response.status_code == 200
    body = response.json()
    assert body["reason"] == INTERRUPTED_REASON
    assert body["memory_written"] is False
    assert experience.memory_writes == []


def test_stop_on_an_already_finished_run_refuses_409(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge())
    store = api.app.state.store
    target_id = _target(store)
    run_id = _claim_checkpointed(store, target_id)
    store.finish_run(run_id, verdict="failed", stopping_condition="turn_cap")   # already finished, for real
    response = api.post(f"/api/runs/{run_id}/stop")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_resumable"


def test_a_refused_stop_writes_nothing_to_the_kept_log(settings, make_client):
    api = make_client(settings, library=fixture_library(), judge=StubJudge())
    store = api.app.state.store
    target_id = _target(store)
    run_id = store.claim_run(target_id, prompt_id="spl-001", prompt_title="t", prompt_text="x",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0")   # a single-turn run: never checkpointed
    response = api.post(f"/api/runs/{run_id}/stop")
    assert response.status_code == 409   # the endpoint's own mode check refuses before any lease or scope opens
    log = api.get(f"/api/runs/{run_id}/log").json()
    assert log["lines"] == []


def test_stop_run_never_reacquires_a_lease_its_caller_already_holds(settings, make_client):  # FR-040
    api = make_client(settings, library=fixture_library(), judge=StubJudge())
    store = api.app.state.store
    target_id = _target(store)
    run_id = _claim_checkpointed(store, target_id)

    app_state = api.app.state
    with lease(app_state, store, run_id):
        run = asyncio.run(stop_run(store, app_state.live_graph, settings, run_id, triggered_by="user"))
    assert run.status == "finished"
