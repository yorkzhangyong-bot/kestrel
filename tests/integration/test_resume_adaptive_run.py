"""The core correctness proof for a resumed adaptive run: at each of four cut points, the in-process exception
itself leaves the row resumable with no restart needed (FR-042), and resuming never repeats an already-durable
attacker/judge call, never duplicates a turn or its evidence, and reaches the same outcome an uninterrupted run
would (FR-005, FR-008, FR-009, FR-010, FR-011, FR-012, FR-036, SC-001). Every cut is a monkeypatched exception
from the real callable the relevant node reaches through `deps` (never the compiled node function itself, which a
graph bakes in at build time and a later monkeypatch of the module attribute would never reach) - the one exception
is the record-commit-window shape, which has no such callable to patch and needs the saver fault-injection
technique T017 established instead (research D6, D13)."""
import asyncio
import dataclasses

import pytest

from kestrel.checkpointing import classify, thread_config
from kestrel.evidence.checker import EvidenceChecker
from kestrel.store import TargetStore
from tests.integration.test_stop_endpoint import _target
from tests.support import StubAttacker, StubJudge, fixture_library, model_settings, real_attacker, real_judge
from tests.unit.test_start_up_sweep_classification import _FailingPutSaver

FEATURE = "014"


def _client(settings, make_client, model_transport, *, max_turns=2):
    # adaptive_max_turns is a Settings field, never a request-body key (RunRequest has no such field - a request
    # body key of that name is silently ignored, ending up driven by whatever Settings already says instead).
    capped = dataclasses.replace(model_settings(settings), adaptive_max_turns=max_turns)
    api = make_client(capped, transport=model_transport.transport, library=fixture_library(),
                      judge=real_judge(model_transport), attacker=real_attacker(model_transport))
    model_transport.verdict = "failed"   # both the cut-and-resumed run and the control reach the same turn_cap
    return api


def _start(api, target_id):
    with pytest.raises(RuntimeError):
        api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak", "mode": "adaptive"})


def _control_outcome(api, target_id):
    """An uninterrupted run of the same script, for comparison (never cut)."""
    response = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                           "mode": "adaptive"})
    assert response.status_code == 201
    body = response.json()
    return body["stopping_condition"], body["verdict"]


@pytest.mark.parametrize("cut", ["attacker_drafted_not_sent", "send_sent_not_checked", "judge_answered_not_recorded"])
def test_each_cut_point_is_in_process_resumable_and_resumes_to_the_same_outcome(
        settings, make_client, model_transport, monkeypatch, cut):
    api = _client(settings, make_client, model_transport)
    store = api.app.state.store
    target_a = _target(store, "A")   # the cut-and-resumed run
    target_b = _target(store, "B")   # the uninterrupted control, same script

    if cut == "attacker_drafted_not_sent":
        # deps.transport is read fresh from app.state at request time (never baked into a default parameter, per
        # the project's own established gotcha about module-level default values) - swapping it here reaches the
        # real send attempt, after the attacker's own draft already committed.
        import httpx
        crashing_transport = httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(
                RuntimeError("simulated crash: attacker drafted, send never completes")))
        monkeypatch.setattr(api.app.state, "transport", crashing_transport)
    elif cut == "send_sent_not_checked":
        async def boom_check(self, turn, reply, remaining):
            raise RuntimeError("simulated crash: send sent, evidence never checks it")
        monkeypatch.setattr(EvidenceChecker, "check_turn", boom_check)
    else:   # judge_answered_not_recorded
        def boom_record(self, run_id, *, position, **fields):
            raise RuntimeError("simulated crash: judge answered, record never writes it")
        monkeypatch.setattr(TargetStore, "add_turn_with_evidence", boom_record)

    _start(api, target_a)
    run_id = store.list_runs(target_a)[0].id

    # Immediately after the cut, before resuming, within the same app instance: resumable, not executing.
    run = store.get_run(run_id)
    assert run.status == "in_progress"
    status = asyncio.run(classify(api.app.state.live_graph, run_id, leased=run_id in api.app.state.leases))
    from kestrel import checkpointing
    assert isinstance(status, checkpointing.Resumable)   # loadable, and read as resumable - never still-executing
    assert run_id not in api.app.state.leases   # released despite the exception

    lines = store.list_log_lines(run_id)
    assert [line.event for line in lines if line.event in ("run.end", "run.interrupted")] == ["run.interrupted"]
    interrupted = [line for line in lines if line.event == "run.interrupted"][0]
    flat = interrupted.record.replace(" ", "")
    assert '"resumable":true' in flat and '"error":"RuntimeError"' in flat
    assert "simulated crash" not in interrupted.record

    monkeypatch.undo()   # the crash was a one-off; resuming must use the real callables again

    response = api.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "finished"

    # No attacker/judge call is repeated for any turn already durably recorded before the cut: exactly one judge
    # call per turn of the *whole* run (turn 1 included, whichever cut point stopped it) - a duplicate judge call
    # for the cut turn would inflate this past turns_used.
    assert len(model_transport.model_requests("judge")) == body["turns_used"]
    # turn 1 never drafts (it is the library seed); one attacker call per turn from turn 2 on.
    assert len(model_transport.model_requests("attacker")) == body["turns_used"] - 1
    turns = store.list_turns(run_id)
    positions = [t.position for t in turns]
    assert positions == sorted(set(positions))   # exactly one row per position, never a duplicate

    control_condition, control_verdict = _control_outcome(api, target_b)
    assert body["stopping_condition"] == control_condition
    assert body["verdict"] == control_verdict


def test_the_record_commit_window_cut_point_is_also_in_process_resumable_and_resumes_cleanly(
        settings, make_client, model_transport):
    # record's own commit window has no deps-reached callable to monkeypatch (it is the one cut point that is pure
    # state logic plus a direct store write, never an external call) - the saver fault-injection technique T017
    # established is what reproduces it instead.
    from kestrel.attack.graph import LIVE_GRAPH

    api = _client(settings, make_client, model_transport)
    store = api.app.state.store
    target_a = _target(store, "A")
    saver = _FailingPutSaver(store, 8)   # judge=failed (default verdict): record's own write lands, decide pending
    api.app.state.live_graph = LIVE_GRAPH.copy(update={"checkpointer": saver})

    _start(api, target_a)
    run_id = store.list_runs(target_a)[0].id
    run = store.get_run(run_id)
    assert run.status == "in_progress"
    status = asyncio.run(classify(api.app.state.live_graph, run_id, leased=run_id in api.app.state.leases))
    from kestrel import checkpointing
    assert isinstance(status, checkpointing.Resumable) and status.from_step == "decide"
    assert run_id not in api.app.state.leases
    assert len(store.list_turns(run_id)) == 1   # record's own write already landed, for real

    from kestrel.checkpointing import KestrelCheckpointSaver
    api.app.state.live_graph = LIVE_GRAPH.copy(update={"checkpointer": KestrelCheckpointSaver(store)})
    response = api.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 200 and response.json()["status"] == "finished"
    assert len(store.list_turns(run_id)) == response.json()["turns_used"]   # never a phantom duplicate turn


def test_secret_scrub_on_the_raw_checkpoint_bytes(settings, make_client, model_transport, tmp_path):
    # FR-033, SC-007: a real auth-header secret value and a distinctive URL/display name never appear in the raw
    # checkpoints/checkpoint_writes bytes, read directly from the database file, cut and resumed.
    api = _client(settings, make_client, model_transport)
    store = api.app.state.store
    secret = "KESTREL-TEST-SECRET-VALUE-ABC123"
    distinctive_url = "http://distinctive-marker-host.kestrel.test/chat"
    from kestrel.api.main import load_terms
    target = store.create_target(name="A", url=distinctive_url, method="POST",
                                 headers=[("X-API-Key", secret)],
                                 body_template='{"message": "{{prompt}}"}', response_path="$.reply",
                                 terms_version=load_terms().version)

    async def boom(self, turn, reply, remaining):
        raise RuntimeError("simulated crash")

    import kestrel.evidence.checker as checker_module
    original = checker_module.EvidenceChecker.check_turn
    checker_module.EvidenceChecker.check_turn = boom
    try:
        with pytest.raises(RuntimeError):
            api.post("/api/runs", json={"target_id": target.id, "family": "system_prompt_leak", "mode": "adaptive"})
    finally:
        checker_module.EvidenceChecker.check_turn = original
    run_id = store.list_runs(target.id)[0].id

    # Read the raw bytes while the checkpoint still exists (before resume finishes the run and deletes it - T035).
    with store.connect() as db:
        rows = db.execute("SELECT checkpoint FROM checkpoints WHERE thread_id = ?", (str(run_id),)).fetchall()
        write_rows = db.execute("SELECT value FROM checkpoint_writes WHERE thread_id = ?",
                                (str(run_id),)).fetchall()
    assert rows or write_rows
    for row in rows:
        blob = bytes(row["checkpoint"])
        assert secret.encode() not in blob and distinctive_url.encode() not in blob
    for row in write_rows:
        blob = bytes(row["value"])
        assert secret.encode() not in blob and distinctive_url.encode() not in blob

    response = api.post(f"/api/runs/{run_id}/resume")
    assert response.status_code == 200
