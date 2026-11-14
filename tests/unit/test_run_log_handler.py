"""The run log handler keeps exactly a live run scope's records in the run's own store: in order, capped at
RUN_LOG_CAP with one `log.truncated` marker, never a run reference's records, and a failing store is one warning and
never an exception (010/FR-010, 010/FR-015, 010/SC-009)."""
import json
import logging
from dataclasses import dataclass

import pytest

from kestrel import events, store as store_module
from kestrel.logging_setup import JsonFormatter, RunLogHandler, configure_logging, reset as reset_logging

FEATURE = "010"


class FakeStore:
    """Records add_log_line calls; `fail` makes every call raise that exception."""

    def __init__(self, fail: Exception | None = None):
        self.rows: list[dict] = []
        self.fail = fail
        self.calls = 0

    def add_log_line(self, run_id, *, seq, ts, event, record):
        self.calls += 1
        if self.fail is not None:
            raise self.fail
        self.rows.append({"run_id": run_id, "seq": seq, "ts": ts, "event": event, "record": record})


@dataclass(frozen=True)
class FakeRun:
    id: int = 7
    target_id: int = 3
    mode: str = "adaptive"
    family: str = "direct_injection"
    verdict: str | None = "failed"
    hard_evidence: bool = False
    stopping_condition: str | None = "turn_cap"
    failure_step: str | None = None
    turns_used: int | None = 1
    tokens_used: int | None = 0
    succeeded_turn: int | None = None


@pytest.fixture
def handler():
    """The run log handler on the `kestrel` logger, beside a StringIO stream rendered by the real JsonFormatter."""
    logger = logging.getLogger("kestrel")
    run_log = RunLogHandler()
    level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(run_log)
    yield run_log
    logger.removeHandler(run_log)
    logger.setLevel(level)


def a_run(store, *, records=0, run_id=7):
    """A live run scope: run.start, `records` retrieval lines, then run.end at the scope's exit."""
    with events.run_scope():
        events.run_started(store, run_id=run_id, target_id=3, mode="adaptive", family="direct_injection")
        for _ in range(records):
            events.emit("memory.retrieval", warm=False, pattern_count=0, memory_count=0, pattern_ids=[])
        events.run_finished(FakeRun(id=run_id))


def test_it_keeps_the_scopes_records_in_order_as_the_exact_json_line(handler, json_log):  # FR-010
    store = FakeStore()
    a_run(store, records=2)
    assert [row["seq"] for row in store.rows] == [1, 2, 3, 4]
    assert [row["event"] for row in store.rows] == ["run.start", "memory.retrieval", "memory.retrieval", "run.end"]
    assert all(row["run_id"] == 7 for row in store.rows)
    assert [row["record"] for row in store.rows] == json_log.text().splitlines()   # what the stream carried
    assert all(json.loads(row["record"])["ts"] == row["ts"] for row in store.rows)


def test_a_run_reference_is_never_kept(handler):  # FR-010
    store = FakeStore()
    with events.run_scope():
        events.run_started(store, run_id=7, target_id=3, mode="adaptive", family="direct_injection")
    before = list(store.rows)
    with events.bind_run_reference(FakeRun(id=7)):
        events.model_request(kind="recommender", model="m", prompt="recommender@1", latency_ms=1, ok=True,
                             status=200, attempts=1, prompt_tokens=1, completion_tokens=1, total_tokens=2)
    assert store.rows == before   # no row, no seq, no counter change


def test_records_outside_any_scope_are_never_kept(handler):  # FR-010
    store = FakeStore()
    events.emit("experiment.start", experiment_id=1, target_id=3, mode="adaptive", families=[], reps=1, max_runs=1,
                token_budget_total=1, wall_clock_s=1, arms=[])
    events.run_started(store, run_id=7, target_id=3, mode="adaptive", family="direct_injection")  # no scope open
    assert store.calls == 0   # no live scope: nothing to keep, and nothing raised


def test_the_cap_keeps_the_first_records_and_marks_the_drop(handler, monkeypatch, json_log):  # FR-010, SC-009
    monkeypatch.setattr(store_module, "RUN_LOG_CAP", 3)
    store = FakeStore()
    a_run(store, records=5)   # run.start + 5 + run.end = 7 records
    assert [row["seq"] for row in store.rows] == [1, 2, 3, 4]
    marker = json.loads(store.rows[-1]["record"])
    assert store.rows[-1]["event"] == "log.truncated" and marker["event"] == "log.truncated"
    assert (marker["kept"], marker["dropped"], marker["run_id"], marker["level"]) == (3, 4, 7, "WARNING")
    assert marker["ts"] == store.rows[-1]["ts"] and marker["target_id"] == 3 and marker["family"] == "direct_injection"
    assert len(json_log.of("memory.retrieval")) == 5 and json_log.of("run.end")   # the stream keeps everything
    assert json_log.of("log.truncated") == []   # the marker is a kept row only


def test_no_marker_without_a_drop(handler, monkeypatch):  # FR-010
    monkeypatch.setattr(store_module, "RUN_LOG_CAP", 4)
    store = FakeStore()
    a_run(store, records=2)   # exactly 4 records: nothing dropped
    assert [row["event"] for row in store.rows][-1] == "run.end" and len(store.rows) == 4


def test_the_shipped_cap_is_1000():  # SC-009
    assert store_module.RUN_LOG_CAP == 1000


def test_a_store_that_raises_is_one_warning_per_error_kind_and_never_an_exception(handler, json_log):
    # FR-015
    store = FakeStore(fail=OSError("disk said no at /private/path"))
    a_run(store, records=3)
    a_run(store, records=2)
    warnings = json_log.of("log.sink_failed")
    assert len(warnings) == 1 and warnings[0]["error"] == "OSError" and warnings[0]["for_run"] == 7
    assert "run_id" not in warnings[0] and warnings[0]["level"] == "WARNING"
    assert "/private/path" not in json_log.text()
    store.fail = ValueError("another kind")
    a_run(store, records=1)
    assert [w["error"] for w in json_log.of("log.sink_failed")] == ["OSError", "ValueError"]


def test_the_handler_formats_with_the_json_formatter(handler):  # FR-010 (D14: one representation)
    assert isinstance(handler.formatter, JsonFormatter)


def test_reset_takes_off_only_the_handlers_configure_logging_installs(settings):  # FR-010
    """Every app's configure_logging installs the stream and the run log handler on the process-wide `kestrel` logger;
    the suite's autouse reset takes them off after each test, or an earlier app's run log handler would keep a later
    test's records a second time (doubled seq, a second marker). A handler Kestrel did not install stays."""
    logger = logging.getLogger("kestrel")
    before, other = list(logger.handlers), logging.NullHandler()
    logger.addHandler(other)
    try:
        configure_logging(settings)
        assert sum(isinstance(h, RunLogHandler) for h in logger.handlers) == 1
        reset_logging()
        assert logger.handlers == before + [other]
    finally:
        logger.removeHandler(other)
