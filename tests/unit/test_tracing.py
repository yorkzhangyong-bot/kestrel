"""The optional tracing adapter (010/FR-013, FR-014, FR-015, SC-004, SC-007): no module-level tracing import; with the
flag off nothing is imported or produced; with the packages missing, one warning and the no-op; with them present, a
private provider, a parentless kestrel.run root and explicitly parented children; a failing or unreachable collector is
one warning and a shutdown bounded to 5 seconds."""
import ast
import dataclasses
import logging
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from kestrel import events, tracing

FEATURE = "010"

OTLP_MODULE = "opentelemetry.exporter.otlp.proto.http.trace_exporter"


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
    tokens_used: int | None = 120
    succeeded_turn: int | None = None


@pytest.fixture
def on(settings):
    return dataclasses.replace(settings, tracing=True)


def traced_run(run_id=7, *, store=None):
    """One run through the event API: a turn with a model request and a target request."""
    with events.run_scope():
        events.run_started(store, run_id=run_id, target_id=3, mode="adaptive", family="direct_injection",
                           attacker_model="a/m", judge_model="j/m", turn_budget=6, token_budget=40000,
                           time_limit_s=300)
        events.turn_started(1)
        with events.child_span("kestrel.target_request") as span:
            events.target_request(latency_ms=5, ok=True, status=200, step="success", reply_chars=10,
                                  reply_truncated=False, span=span)
        with events.child_span("kestrel.model_request") as span:
            events.model_request(kind="judge", model="j/m", prompt="judge@1", latency_ms=9, ok=True, status=200,
                                 attempts=1, prompt_tokens=100, completion_tokens=20, total_tokens=120,
                                 verdict="failed", span=span)
        events.turn_ended(turn=1, source="library:dir-001", message_chars=10, reply_chars=10, reply_truncated=False,
                          canary_hit=False, hard_evidence=False, judged=True, verdict="failed",
                          attacker_generated=False)
        events.run_finished(FakeRun(id=run_id))


def finished(collector):
    tracing.current().force_flush()
    return collector.get_finished_spans()


def test_the_module_has_no_module_level_tracing_import():  # FR-014
    tree = ast.parse(Path(tracing.__file__).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert not any(alias.name.startswith("opentelemetry") for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("opentelemetry")


def test_flag_off_imports_nothing_and_warns_nothing(settings, monkeypatch, json_log):  # FR-014, SC-004
    monkeypatch.setitem(sys.modules, OTLP_MODULE, None)   # importing it would raise
    tracer = tracing.configure_tracing(settings)
    assert tracer.enabled is False and tracing.current() is tracer
    traced_run()
    assert json_log.of("tracing.unavailable") == []


def test_flag_on_without_the_packages_is_one_warning_and_the_no_op(on, monkeypatch, json_log):  # FR-014, SC-007
    monkeypatch.setitem(sys.modules, OTLP_MODULE, None)
    tracer = tracing.configure_tracing(on)
    assert tracer.enabled is False
    traced_run()   # the run is untouched
    warnings = json_log.of("tracing.unavailable")
    assert len(warnings) == 1 and warnings[0]["level"] == "WARNING"
    assert (warnings[0]["cause"], warnings[0]["extra"]) == ("package_missing", "kestrel[otel]")


def test_a_run_is_one_trace_with_a_parentless_root_and_parented_children(on, span_collector):  # FR-013, SC-004
    from opentelemetry import trace
    global_provider = trace.get_tracer_provider()
    tracing.configure_tracing(on, exporter=span_collector)
    traced_run(run_id=7)
    spans = finished(span_collector)
    by_name = {span.name: span for span in spans}
    assert sorted(by_name) == ["kestrel.model_request", "kestrel.run", "kestrel.target_request", "kestrel.turn"]
    root, turn = by_name["kestrel.run"], by_name["kestrel.turn"]
    assert root.parent is None and root.attributes["kestrel.run_id"] == 7
    assert root.attributes["kestrel.verdict"] == "failed" and root.attributes["kestrel.judge_used"] is False
    assert turn.parent.span_id == root.context.span_id and turn.attributes["kestrel.turn"] == 1
    for child in ("kestrel.model_request", "kestrel.target_request"):
        assert by_name[child].parent.span_id == turn.context.span_id
    assert len({span.context.trace_id for span in spans}) == 1
    model = by_name["kestrel.model_request"].attributes
    assert (model["kestrel.kind"], model["kestrel.prompt"], model["gen_ai.request.model"]) == ("judge", "judge@1", "j/m")
    assert (model["gen_ai.usage.input_tokens"], model["gen_ai.usage.output_tokens"]) == (100, 20)
    assert root.resource.attributes["service.name"] == "kestrel"
    assert trace.get_tracer_provider() is global_provider   # private: never installed globally


def test_two_runs_are_two_traces(on, span_collector):  # FR-013, SC-004
    tracing.configure_tracing(on, exporter=span_collector)
    traced_run(run_id=1)
    traced_run(run_id=2)
    roots = [span for span in finished(span_collector) if span.name == "kestrel.run"]
    assert sorted(root.attributes["kestrel.run_id"] for root in roots) == [1, 2]
    assert len({root.context.trace_id for root in roots}) == 2 and all(root.parent is None for root in roots)


def test_the_service_name_follows_the_standard_variable(on, span_collector, monkeypatch):  # FR-013
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    monkeypatch.setenv("OTEL_SERVICE_NAME", "kestrel-staging")
    tracing.configure_tracing(on, exporter=InMemorySpanExporter())
    tracing.configure_tracing(on, exporter=span_collector)   # callable again in one process (the first is shut down)
    traced_run()
    assert finished(span_collector)[0].resource.attributes["service.name"] == "kestrel-staging"


def test_nothing_is_traced_outside_a_run(on, span_collector):  # FR-013 (no other span)
    tracing.configure_tracing(on, exporter=span_collector)
    with events.bind_run_reference(FakeRun()):
        with events.child_span("kestrel.model_request") as span:
            assert span is None   # the recommender at report time is logged, not traced
    events.connection_test(target_id=None, latency_ms=1, ok=True, status=200, step="success")
    assert finished(span_collector) == ()


class Raises:
    def export(self, spans):
        raise ConnectionError("collector at http://private.example:4318 refused")

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=30000):
        return True


class Refuses(Raises):
    def export(self, spans):
        from opentelemetry.sdk.trace.export import SpanExportResult
        return SpanExportResult.FAILURE


@pytest.mark.parametrize("exporter, error", [(Raises(), "ConnectionError"), (Refuses(), "failure_result")])
def test_a_failing_exporter_is_one_warning_and_never_an_exception(on, json_log, exporter, error):  # FR-015
    tracing.configure_tracing(on, exporter=exporter)
    traced_run(run_id=1)
    tracing.current().force_flush()
    traced_run(run_id=2)
    tracing.current().force_flush()
    warnings = json_log.of("tracing.export_failed")
    assert len(warnings) == 1 and warnings[0]["error"] == error and warnings[0]["level"] == "WARNING"
    assert "private.example" not in json_log.text()


def test_the_sdk_logs_never_reach_the_stream(on, span_collector, capfd):  # FR-015
    """The SDK's own lines (plain text, possibly repeated) neither propagate to the root logger nor fall through to
    logging's last-resort stderr handler: Kestrel's guard reports a failure once, as JSON. (A probe on the root logger,
    not caplog: pytest attaches its capture handler to non-propagating loggers too.)"""
    tracing.configure_tracing(on, exporter=span_collector)
    seen = []

    class Probe(logging.Handler):
        def emit(self, record):
            seen.append(record)

    probe, root = Probe(), logging.getLogger()
    root.addHandler(probe)
    try:
        logging.getLogger("opentelemetry.sdk.trace").warning("an SDK line")
    finally:
        root.removeHandler(probe)
    assert logging.getLogger("opentelemetry").propagate is False
    assert seen == [] and "an SDK line" not in capfd.readouterr().err


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]   # closed once this block exits: nothing listens there


@pytest.mark.real_otlp_exporter
def test_an_unreachable_collector_leaves_the_run_unchanged_and_shutdown_is_bounded(on, monkeypatch, json_log):
    # FR-013, FR-015, SC-004: the real OTLP/HTTP exporter, the standard variables, a closed local port
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{_closed_port()}")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TIMEOUT", "1")
    tracer = tracing.configure_tracing(on)
    assert tracer.enabled is True
    traced_run(run_id=1)
    started = time.monotonic()
    tracer.shutdown(5.0)
    assert time.monotonic() - started < 5.5
    warnings = json_log.of("tracing.export_failed")
    assert len(warnings) == 1 and warnings[0]["error"] in ("failure_result", "ConnectionError", "ConnectError")
    assert [r["event"] for r in json_log() if r.get("run_id") == 1][-1] == "run.end"   # the run itself unchanged


def test_shutdown_is_bounded_whatever_the_provider_does(on, span_collector):  # FR-015
    tracer = tracing.configure_tracing(on, exporter=span_collector)

    class Stuck:
        def shutdown(self):
            time.sleep(30)

        def force_flush(self, timeout_millis=None):
            time.sleep(30)

    tracer._provider = Stuck()
    started = time.monotonic()
    tracer.shutdown(0.5)
    tracer.force_flush(0.5)
    assert time.monotonic() - started < 2.0
