"""The idle auto-stop, reinforced for a genuinely paused run (014/FR-058, FR-059, FR-060, FR-061): with the
approve node shipped, pause a run through the real checkbox and the real `interrupt()` - never T061's own
monkeypatched stand-in - and advance the clock past the configured window; the identical, already-generic
mechanism stops it with the identical outcome and logging. Proof of composition, no part-2 production code of its
own (research D1).
"""
import asyncio
from datetime import datetime, timezone

from kestrel.api.main import check_idle_runs
from tests.integration.test_approve_node_live import _api, _start_paused
from tests.integration.test_idle_auto_stop import FakeClock, _app_state, _graph, _idle_settings
from tests.integration.test_stop_endpoint import _target

FEATURE = "014"


def test_a_genuinely_paused_run_is_auto_stopped_by_the_same_mechanism(settings, make_client, model_transport):
    # Pause through the real checkbox (POST /api/runs with ask_before_each_turn=True, the real approve node's own
    # interrupt), never a monkeypatched check_turn.
    api = _api(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)
    run_id = _start_paused(api, target_id)["id"]
    assert store.get_run(run_id).status == "in_progress"

    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    store.touch_last_activity(run_id, now=clock())
    app_state = _app_state(store, clock)
    clock.advance(hours=3)   # past the 2h window (and past the 1h restart grace period)
    asyncio.run(check_idle_runs(store, _graph(store), _idle_settings(settings), app_state))

    auto = store.get_run(run_id)
    assert auto.status == "finished"
    assert auto.stopping_condition == "stopped_by_user"   # the ordinary shape, identically to a manual Stop

    # Identical logging: one run.stopped naming the automatic trigger and the elapsed hours, and exactly one
    # run.end - the automatic check opened its own scope around this one stop.
    seen = {line.event: line for line in store.list_log_lines(run_id)}
    stopped = [line for line in store.list_log_lines(run_id) if line.event == "run.stopped"]
    assert len(stopped) == 1
    flat = stopped[0].record.replace(" ", "")
    assert '"trigger":"idle_timeout"' in flat and '"idle_hours":2.0' in flat
    assert '"was_paused":true' in flat   # this run was genuinely paused when it was stopped
    assert len([line for line in store.list_log_lines(run_id) if line.event == "run.end"]) == 1
