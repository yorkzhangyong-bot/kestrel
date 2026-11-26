"""The approve-node's own events (014/FR-026, FR-033, FR-046, research D21): `run.paused` names the turn, emitted
exactly once per actual pause (a bare status re-check never re-emits it); `run.decided` names the turn and the
decision; `run.stopped` names whether the run was paused or merely resumable, and whether it was the reconciled
case; none carries the pending message's text; a decision-routed Stop opens exactly one scope (one `run.decided`,
one `run.end`, never a nested second pair).
"""
import inspect
import logging

import pytest

from kestrel import events
from tests.integration.test_approve_node_live import _api, _start_paused
from tests.integration.test_stop_endpoint import _target

FEATURE = "014"


@pytest.fixture
def records():
    """Every LogRecord the `kestrel` logger handles (the same collector `test_events.py` uses)."""
    class Collect(logging.Handler):
        def __init__(self):
            super().__init__()
            self.items = []

        def emit(self, record):
            self.items.append(record)

    logger = logging.getLogger("kestrel")
    handler, level = Collect(), logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    yield handler.items
    logger.removeHandler(handler)
    logger.setLevel(level)


def _fields(record):
    return record.kestrel_fields


def test_run_paused_names_the_turn(records):
    events.run_paused(turn=2)
    assert [r.kestrel_event for r in records] == ["run.paused"]
    assert _fields(records[0])["turn"] == 2


def test_run_decided_names_the_turn_and_the_decision(records):
    events.run_decided(turn=2, decision="approve")
    assert [r.kestrel_event for r in records] == ["run.decided"]
    line = _fields(records[0])
    assert line["turn"] == 2 and line["decision"] == "approve"


def test_run_stopped_names_paused_reconciled_and_trigger(records):
    events.run_stopped(was_paused=True, reconciled=False, trigger="user")
    assert [r.kestrel_event for r in records] == ["run.stopped"]
    line = _fields(records[0])
    assert line["was_paused"] is True and line["reconciled"] is False and line["trigger"] == "user"
    assert "idle_hours" not in line   # idle_hours only when triggered automatically


def test_no_approve_event_takes_a_message_parameter_at_all(records):
    # None of the three helpers even accepts a message - the pending message lives on the run's own page only.
    for helper in (events.run_paused, events.run_decided, events.run_stopped):
        assert not set(inspect.signature(helper).parameters) & {"message", "text", "reply", "attack"}


def test_a_stop_decision_opens_exactly_one_scope(settings, make_client, model_transport):
    # 014/FR-046: decide "stop" on a paused run and read the kept log - exactly one run.decided and exactly one
    # run.end, never a nested second scope from stop_run emitting its own independent pair for the same request.
    api = _api(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)
    run_id = _start_paused(api, target_id)["id"]

    response = api.post(f"/api/runs/{run_id}/decision", json={"turn": 2, "decision": "stop"})
    assert response.status_code == 200

    seen = [line.event for line in store.list_log_lines(run_id)]
    assert seen.count("run.decided") == 1
    assert seen.count("run.end") == 1
    assert "run.interrupted" not in seen


def test_a_pause_is_recorded_once_and_a_status_recheck_does_not_reemit(settings, make_client, model_transport):
    # research D21: run.paused is emitted once when the graph actually pauses; a read-only status re-check (GET
    # /api/runs/{id}) must not re-emit it.
    api = _api(settings, make_client, model_transport)
    store = api.app.state.store
    target_id = _target(store)
    run_id = _start_paused(api, target_id)["id"]

    assert [line.event for line in store.list_log_lines(run_id)].count("run.paused") == 1
    api.get(f"/api/runs/{run_id}")   # the read-only classification, never a graph invocation
    assert [line.event for line in store.list_log_lines(run_id)].count("run.paused") == 1
