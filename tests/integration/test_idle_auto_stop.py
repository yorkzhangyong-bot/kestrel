"""The periodic idle-stop check: three Stop shapes auto-stopped identically to a manual `/stop` on the same
persisted state (only `reason`, `trigger` and `idle_hours` differ), a not-yet-due row never even leased, a leased
row skipped without blocking, per-row failure isolation, and loop/tick survival (014/FR-058, FR-059, FR-060,
SC-021, research D26, D27, D29)."""
import asyncio
import dataclasses
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from kestrel import checkpointing, events
from kestrel.api.main import check_idle_runs
from kestrel.attack.graph import LIVE_GRAPH, _initial_state
from kestrel.checkpointing import KestrelCheckpointSaver
from kestrel.evidence.checker import EvidenceChecker
from tests.integration.test_stop_endpoint import _claim_checkpointed, _target
from tests.support import StubAttacker, StubJudge, fixture_library
from tests.unit.test_adaptive_graph_state import make_deps, numbered_sender
from tests.unit.test_start_up_sweep_classification import _FailingPutSaver

FEATURE = "014"

IDLE_HOURS = 2.0


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


def _app_state(store, clock, started_at=None):
    return SimpleNamespace(leases=set(), accepted_exits=set(), clock=clock,
                           started_at=started_at or (clock() - timedelta(hours=2)), store=store)


def _idle_settings(settings, *, resume_idle_hours=IDLE_HOURS):
    return dataclasses.replace(settings, resume_idle_hours=resume_idle_hours)


def _resumable_run(store, name="A"):
    """send done, evidence pending - no outcome decided yet (the "ordinary" shape)."""
    target_id = _target(store, name)
    run_id = _claim_checkpointed(store, target_id)
    saver = _FailingPutSaver(store, 3)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = dataclasses.replace(
        make_deps(store=store, sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                 attacker=StubAttacker(), max_turns=2),
        run_id=run_id)
    config = {"configurable": {"thread_id": str(run_id)}}
    with pytest.raises(RuntimeError):
        asyncio.run(copied.ainvoke(_initial_state(), config, context=deps, durability="sync"))
    return run_id


def _reached_end_run(store, name="B"):
    """A full, natural finish via the graph, never durably finished (the "reconciled" shape)."""
    target_id = _target(store, name)
    run_id = _claim_checkpointed(store, target_id)
    saver = KestrelCheckpointSaver(store)
    copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
    deps = dataclasses.replace(
        make_deps(store=store, sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                 attacker=StubAttacker(), max_turns=1),
        run_id=run_id)
    asyncio.run(copied.ainvoke(_initial_state(), {"configurable": {"thread_id": str(run_id)}}, context=deps,
                              durability="sync"))
    return run_id


def _no_checkpoint_run(store, name="C"):
    target_id = _target(store, name)
    return _claim_checkpointed(store, target_id)   # claimed, never driven: no checkpoint at all


def _paused_run(store, name="D", monkeypatch=None):
    from langgraph.types import interrupt

    async def pausing_check_turn(self, turn, reply, remaining):
        interrupt({"turn": turn, "message": "paused for testing"})
        raise AssertionError("unreachable")

    original = EvidenceChecker.check_turn
    EvidenceChecker.check_turn = pausing_check_turn
    try:
        target_id = _target(store, name)
        run_id = _claim_checkpointed(store, target_id)
        saver = KestrelCheckpointSaver(store)
        copied = LIVE_GRAPH.copy(update={"checkpointer": saver})
        deps = dataclasses.replace(
            make_deps(store=store, sender=numbered_sender(), judge=StubJudge(verdict="failed"),
                     attacker=StubAttacker(), max_turns=2),
            run_id=run_id)
        asyncio.run(copied.ainvoke(_initial_state(), {"configurable": {"thread_id": str(run_id)}}, context=deps,
                                  durability="sync"))
    finally:
        EvidenceChecker.check_turn = original
    return run_id


def _graph(store):
    return LIVE_GRAPH.copy(update={"checkpointer": KestrelCheckpointSaver(store)})


def _real_store(settings):
    from cryptography.fernet import Fernet
    from kestrel.secrets import Vault
    from kestrel.store import TargetStore
    return TargetStore(settings.db_path, Vault(Fernet.generate_key()))


# ---- not-yet-due: never stopped ----


@pytest.mark.parametrize("builder", [_resumable_run, _reached_end_run])
def test_a_not_yet_due_run_of_each_shape_is_not_stopped(settings, builder):
    store = _real_store(settings)
    run_id = builder(store)
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    store.touch_last_activity(run_id, now=clock())
    app_state = _app_state(store, clock)
    clock.advance(hours=1)   # idle 1h < the 2h window: not due
    asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))
    assert store.get_run(run_id).status == "in_progress"


def test_a_not_yet_due_paused_run_is_not_stopped(settings):
    store = _real_store(settings)
    run_id = _paused_run(store)
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    store.touch_last_activity(run_id, now=clock())
    app_state = _app_state(store, clock)
    clock.advance(hours=1)
    asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))
    assert store.get_run(run_id).status == "in_progress"


def test_not_yet_due_run_is_never_leased(settings):
    store = _real_store(settings)
    run_id = _resumable_run(store)
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    store.touch_last_activity(run_id, now=clock())
    app_state = _app_state(store, clock)
    clock.advance(hours=1)

    original_lease = checkpointing.lease
    attempted = []

    def spying_lease(app_state_arg, store_arg, rid):
        attempted.append(rid)
        return original_lease(app_state_arg, store_arg, rid)

    import kestrel.api.main as main_module
    saved = main_module.checkpointing.lease
    main_module.checkpointing.lease = spying_lease
    try:
        asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))
    finally:
        main_module.checkpointing.lease = saved
    assert run_id not in attempted


# ---- the three auto-stop shapes, each compared field-by-field against a manual /stop ----


def test_the_ordinary_shape_auto_stops_identically_to_a_manual_stop_except_reason(settings, make_client):
    store_a = _real_store(settings)
    run_a = _resumable_run(store_a, "A")

    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    store_a.touch_last_activity(run_a, now=clock())
    app_state = _app_state(store_a, clock)
    clock.advance(hours=3)   # past the 2h window
    asyncio.run(check_idle_runs(store_a, _graph(store_a), _idle_settings(settings), app_state))
    auto = store_a.get_run(run_a)
    assert auto.status == "finished"

    # The manual comparison run is built through the app only after `make_client` has returned, so the one-time
    # start-up sweep (which runs at `make_client`) never sees it first (test_stop_endpoint's own note).
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    run_b = _resumable_run(api.app.state.store, "A2")
    manual_response = api.post(f"/api/runs/{run_b}/stop")
    assert manual_response.status_code == 200
    manual = api.app.state.store.get_run(run_b)

    for field in ("status", "verdict", "turns_used", "tokens_used", "stopping_condition", "hard_evidence",
                 "judge_used"):
        assert getattr(auto, field) == getattr(manual, field), field
    assert auto.reason != manual.reason   # the one field that differs: the automatic sentence vs "stopped_by_user"
    assert "hours" in auto.reason and f"{IDLE_HOURS:g}" in auto.reason


def test_the_reconciled_shape_auto_stops_identically_to_a_manual_stop_including_reason(settings, make_client):
    store = _real_store(settings)
    run_a = _reached_end_run(store, "A")

    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    store.touch_last_activity(run_a, now=clock())
    app_state = _app_state(store, clock)
    clock.advance(hours=3)
    asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))
    auto = store.get_run(run_a)
    assert auto.status == "finished" and auto.stopping_condition != "stopped_by_user"

    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    run_b = _reached_end_run(api.app.state.store, "A2")
    manual_response = api.post(f"/api/runs/{run_b}/stop")
    assert manual_response.status_code == 200
    manual = api.app.state.store.get_run(run_b)

    for field in ("status", "verdict", "turns_used", "tokens_used", "stopping_condition", "reason", "hard_evidence"):
        assert getattr(auto, field) == getattr(manual, field), field   # reason too: never becomes stopped_by_user


def test_the_no_checkpoint_shape_auto_stops_identically_to_a_manual_stop(settings, make_client):
    store = _real_store(settings)
    run_a = _no_checkpoint_run(store, "A")

    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    store.touch_last_activity(run_a, now=clock())
    app_state = _app_state(store, clock)
    clock.advance(hours=3)
    asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))
    auto = store.get_run(run_a)

    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    run_b = _no_checkpoint_run(api.app.state.store, "A2")
    manual_response = api.post(f"/api/runs/{run_b}/stop")
    assert manual_response.status_code == 200
    manual = api.app.state.store.get_run(run_b)
    assert auto.stopping_condition == manual.stopping_condition and auto.reason == manual.reason


def test_every_auto_stop_logs_trigger_idle_timeout_the_manual_one_logs_trigger_user(settings, make_client, json_log):
    store = _real_store(settings)
    run_a = _resumable_run(store, "A")
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    store.touch_last_activity(run_a, now=clock())
    app_state = _app_state(store, clock)
    clock.advance(hours=3)
    asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))
    auto_lines = [r for r in json_log() if r.get("event") == "run.stopped" and r.get("run_id") == run_a]
    assert len(auto_lines) == 1
    assert auto_lines[0]["trigger"] == "idle_timeout" and auto_lines[0]["idle_hours"] == IDLE_HOURS

    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    api.app.state.store = store
    run_b = _resumable_run(store, "B")
    api.post(f"/api/runs/{run_b}/stop")
    manual_lines = [r for r in json_log() if r.get("event") == "run.stopped" and r.get("run_id") == run_b]
    assert len(manual_lines) == 1
    assert manual_lines[0]["trigger"] == "user" and "idle_hours" not in manual_lines[0]


def test_the_auto_stopped_runs_kept_log_has_one_run_stopped_and_exactly_one_run_end(settings):
    from kestrel.logging_setup import configure_logging

    configure_logging(settings)   # install the run log handler this direct (non-app) check keeps lines through
    store = _real_store(settings)
    run_id = _resumable_run(store)
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    store.touch_last_activity(run_id, now=clock())
    app_state = _app_state(store, clock)
    clock.advance(hours=3)
    asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))
    lines = store.list_log_lines(run_id)
    assert len([l for l in lines if l.event == "run.stopped"]) == 1
    assert len([l for l in lines if l.event == "run.end"]) == 1


# ---- leased: skipped, never blocked ----


def test_a_currently_leased_run_is_skipped_never_blocked_then_stopped_at_the_next_check(settings):
    store = _real_store(settings)
    run_id = _resumable_run(store)
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    store.touch_last_activity(run_id, now=clock())
    app_state = _app_state(store, clock)
    clock.advance(hours=3)

    with checkpointing.lease(app_state, store, run_id):
        asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))
    assert store.get_run(run_id).status == "in_progress"   # skipped, not blocked - the check itself returned

    asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))
    assert store.get_run(run_id).status == "finished"   # the next check catches it, lease released through its exit


def test_the_recheck_under_the_lease_race_a_reset_clock_in_the_gap_is_respected(settings, monkeypatch):
    store = _real_store(settings)
    run_id = _resumable_run(store)
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    store.touch_last_activity(run_id, now=clock())
    app_state = _app_state(store, clock)
    clock.advance(hours=3)

    original_lease = checkpointing.lease

    def resetting_lease(app_state_arg, store_arg, rid):
        if rid == run_id:
            store_arg.touch_last_activity(rid, now=clock())   # simulates a concurrent accepted resume landing
        return original_lease(app_state_arg, store_arg, rid)

    import kestrel.api.main as main_module
    monkeypatch.setattr(main_module.checkpointing, "lease", resetting_lease)
    asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))
    assert store.get_run(run_id).status == "in_progress"   # the re-read under the lease saw the reset


# ---- per-row failure isolation and loop/tick survival ----


def test_a_failed_automatic_stop_is_retried_without_backoff_and_logs_no_kept_line(settings, monkeypatch):
    store = _real_store(settings)
    run_id = _resumable_run(store)
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    store.touch_last_activity(run_id, now=clock())
    app_state = _app_state(store, clock)
    clock.advance(hours=3)
    before = store.get_run(run_id).last_activity_at

    import kestrel.api.main as main_module

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated stop failure")
    monkeypatch.setattr(main_module, "stop_run", boom)
    asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))
    assert store.get_run(run_id).status == "in_progress"
    assert store.get_run(run_id).last_activity_at == before   # the failed attempt never touches the idle clock
    lines = store.list_log_lines(run_id)
    assert [l.event for l in lines] == []   # no kept run.interrupted, no run.end - only the unscoped check_failed

    monkeypatch.setattr(main_module, "stop_run", main_module.stop_run.__wrapped__
                        if hasattr(main_module.stop_run, "__wrapped__") else _real_stop_run())
    asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))
    assert store.get_run(run_id).status == "finished"   # retried, not skipped, not deferred


def _real_stop_run():
    from kestrel.runs import stop_run
    return stop_run


def test_one_runs_failure_does_not_end_the_check_or_block_a_later_row(settings, monkeypatch, json_log):
    store = _real_store(settings)
    failing_run = _resumable_run(store, "A")
    second_run = _resumable_run(store, "B")
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    for rid in (failing_run, second_run):
        store.touch_last_activity(rid, now=clock())
    app_state = _app_state(store, clock)
    clock.advance(hours=3)

    import kestrel.api.main as main_module
    real_stop_run = main_module.stop_run

    async def selectively_failing(store_arg, graph_arg, settings_arg, rid, *, triggered_by):
        if rid == failing_run:
            raise RuntimeError("simulated failure for this one row")
        return await real_stop_run(store_arg, graph_arg, settings_arg, rid, triggered_by=triggered_by)

    monkeypatch.setattr(main_module, "stop_run", selectively_failing)
    asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))
    assert store.get_run(failing_run).status == "in_progress"
    assert store.get_run(second_run).status == "finished"   # not blocked by the first row's own failure
    failed_lines = [r for r in json_log() if r.get("event") == "idle_stop.check_failed"]
    assert any(r.get("run_id") == failing_run and r.get("exc_type") == "RuntimeError" for r in failed_lines)

    # A third, overdue run seeded only after this tick is still stopped at the next one.
    third_run = _resumable_run(store, "C")
    store.touch_last_activity(third_run, now=clock())
    clock.advance(hours=3)   # idle 3h >= the 2h window: due at the next tick
    monkeypatch.setattr(main_module, "stop_run", real_stop_run)
    asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))
    assert store.get_run(failing_run).status == "finished"
    assert store.get_run(third_run).status == "finished"


def test_a_listing_failure_does_not_end_the_loop_run_id_omitted_entirely(settings, monkeypatch, json_log):
    store = _real_store(settings)
    run_id = _resumable_run(store)
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    store.touch_last_activity(run_id, now=clock())
    app_state = _app_state(store, clock)
    clock.advance(hours=3)

    calls = {"n": 0}
    original_listing = store.list_in_progress_checkpointed_runs

    def failing_once():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated listing failure")
        return original_listing()

    monkeypatch.setattr(store, "list_in_progress_checkpointed_runs", failing_once)
    asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))
    assert store.get_run(run_id).status == "in_progress"   # this tick stopped nothing
    failed_lines = [r for r in json_log() if r.get("event") == "idle_stop.check_failed"]
    assert failed_lines and "run_id" not in failed_lines[-1]

    asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))
    assert store.get_run(run_id).status == "finished"   # the next tick catches the same, still-overdue run
