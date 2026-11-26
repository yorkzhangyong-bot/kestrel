"""The idle clock: `last_activity_at` at claim time, reset only by an accepted exit, the restart grace period
(014/FR-059, research D26, D27)."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cryptography.fernet import Fernet

from kestrel.api.main import check_idle_runs
from kestrel.checkpointing import lease, mark_active
from kestrel.secrets import Vault
from kestrel.settings import Settings
from kestrel.store import TargetStore, _iso
from tests.integration.test_stop_endpoint import _claim_checkpointed, _target

FEATURE = "014"


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


def _store(tmp_path) -> TargetStore:
    return TargetStore(tmp_path / "kestrel.db", Vault(Fernet.generate_key()))


def _app_state(clock, started_at=None):
    return SimpleNamespace(leases=set(), accepted_exits=set(), clock=clock,
                           started_at=started_at or clock())


def _settings(tmp_path, *, resume_idle_hours=2.0):
    return Settings(mode="local", db_path=tmp_path / "kestrel.db", key_file=tmp_path / "key", secret_key=None,
                    resume_idle_hours=resume_idle_hours)


def test_a_fresh_claims_last_activity_at_equals_the_claim_moment(tmp_path):
    store = _store(tmp_path)
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    target_id = _target(store)
    run_id = store.claim_run(target_id, prompt_id="spl-001", prompt_title="t", prompt_text="x",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0", now=clock())
    run = store.get_run(run_id)
    assert run.last_activity_at == _iso(clock())


def test_an_accepted_exit_resets_the_clock_a_refused_one_never_does(tmp_path):
    store = _store(tmp_path)
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    app_state = _app_state(clock)
    target_id = _target(store)
    run_id = store.claim_run(target_id, prompt_id="spl-001", prompt_title="t", prompt_text="x",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0", now=clock())
    original = store.get_run(run_id).last_activity_at

    clock.advance(hours=1)
    with lease(app_state, store, run_id):
        pass   # refused: no mark_active call (e.g. a precondition refusal before anything was attempted)
    assert store.get_run(run_id).last_activity_at == original

    clock.advance(hours=1)
    with lease(app_state, store, run_id):
        mark_active(app_state, run_id)   # accepted: a pause, a survived error, or an accepted resume/decision/stop
    assert store.get_run(run_id).last_activity_at == _iso(clock())


def test_claim_runs_own_clock_agrees_with_app_state_clock_never_a_second_wall_clock_read(tmp_path):
    store = _store(tmp_path)
    simulated = datetime(2030, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    target_id = _target(store)
    run_id = store.claim_run(target_id, prompt_id="spl-001", prompt_title="t", prompt_text="x",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0", now=simulated)
    assert store.get_run(run_id).last_activity_at == _iso(simulated)


def test_the_restart_grace_period_is_a_complete_no_op_no_row_even_read(tmp_path, monkeypatch):
    store = _store(tmp_path)
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = FakeClock(started)
    app_state = _app_state(clock, started_at=started)
    settings = _settings(tmp_path, resume_idle_hours=2.0)

    def boom():
        raise AssertionError("the listing must never be read during the grace period")
    monkeypatch.setattr(store, "list_in_progress_checkpointed_runs", boom)

    clock.advance(minutes=59)   # < min(1h, 2h) since started_at
    asyncio.run(check_idle_runs(store, None, settings, app_state))   # graph is never touched either: no raise


def test_once_the_grace_period_elapses_an_overdue_run_is_caught_at_the_next_check(tmp_path):
    from kestrel.attack.graph import LIVE_GRAPH
    from kestrel.checkpointing import KestrelCheckpointSaver

    store = _store(tmp_path)
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = FakeClock(started)
    app_state = _app_state(clock, started_at=started)
    settings = _settings(tmp_path, resume_idle_hours=2.0)
    graph = LIVE_GRAPH.copy(update={"checkpointer": KestrelCheckpointSaver(store)})

    target_id = _target(store)
    run_id = _claim_checkpointed(store, target_id)
    store.touch_last_activity(run_id, now=clock())   # idle from "started", like a resumable row left by the sweep

    clock.advance(minutes=30)   # still within the grace period (< 1h)
    asyncio.run(check_idle_runs(store, graph, settings, app_state))
    assert store.get_run(run_id).status == "in_progress"   # not yet even read

    clock.advance(hours=2)   # past the grace period, and past resume_idle_hours since last_activity_at
    asyncio.run(check_idle_runs(store, graph, settings, app_state))
    finished = store.get_run(run_id)
    assert finished.status == "finished"
    # No checkpoint was ever written for this run, so stop_run's NoCheckpoint branch closes it - the identical
    # reason text the manual path and the sweep both use, regardless of what triggered it (research D29).
    from kestrel.runs import INTERRUPTED_REASON
    assert finished.reason == INTERRUPTED_REASON
