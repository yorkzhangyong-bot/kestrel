"""Logging and tracing can never harm a run (010/FR-015, 010/FR-017, 010/SC-005): the same stub adaptive run with a
working sink, a sink that raises on every write and an exporter that raises reaches the same verdict, evidence,
stopping condition, turns and tokens, with the same calls to the target, the attacker and the judge — and each
failure is exactly one warning. Stubs suffice: outcomes only; placeholders only."""
import dataclasses
import logging
import uuid

import httpx

from tests.support import StubAttacker, StubJudge, fixture_library, saved_target

FEATURE = "010"


class RaisingExporter:
    def export(self, spans):
        raise ConnectionError("the collector is down")

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=30000):
        return True


def stub_run(make_client, settings, monkeypatch, *, failing_sink=False, failing_exporter=False, exporter=None,
             prepare=None):
    """One stub adaptive run through the API; returns its outcome and the calls it made."""
    sent = []

    def target(request):
        sent.append(request)
        return httpx.Response(200, json={"reply": "an ordinary answer"})

    attacker, judge = StubAttacker(tokens=100), StubJudge(verdict="failed")
    exporter = RaisingExporter() if failing_exporter else exporter
    own = settings.db_path.parent / uuid.uuid4().hex[:8]   # each run on a fresh database and store, alike
    app_settings = dataclasses.replace(settings, adaptive_max_turns=3, tracing=exporter is not None,
                                       db_path=own / "kestrel.db", chroma_path=own / "chroma")
    api = make_client(app_settings, transport=httpx.MockTransport(target), library=fixture_library(), judge=judge,
                      attacker=attacker, span_exporter=exporter)
    store = api.app.state.store
    if failing_sink:
        def broken(*args, **kwargs):
            raise OSError("the run log cannot be written")
        monkeypatch.setattr(store, "add_log_line", broken)
    if prepare is not None:
        prepare()
    target_row = saved_target(store)
    run = api.post("/api/runs", json={"target_id": target_row.id, "family": "system_prompt_leak",
                                      "mode": "adaptive"}).json()
    if exporter is not None:
        from kestrel import tracing
        tracing.current().force_flush()
    outcome = {key: run[key] for key in ("verdict", "hard_evidence", "stopping_condition", "turns_used",
                                         "tokens_used", "status")}
    calls = {"target": len(sent), "attacker": len(attacker.calls), "judge": len(judge.calls)}
    return outcome, calls, api, run


def test_a_failing_sink_or_exporter_changes_nothing_about_the_run(make_client, settings, monkeypatch, json_log):
    # FR-015, FR-017, SC-005
    working, working_calls, _, _ = stub_run(make_client, settings, monkeypatch)
    sink, sink_calls, _, _ = stub_run(make_client, settings, monkeypatch, failing_sink=True)
    exporter, exporter_calls, _, _ = stub_run(make_client, settings, monkeypatch, failing_exporter=True)
    assert working == sink == exporter
    assert working_calls == sink_calls == exporter_calls        # logging and tracing add no call
    assert working["status"] == "finished" and working["turns_used"] == 3
    assert working["tokens_used"] == 100 * working_calls["attacker"]   # only the stubs' tokens: none for logging
    assert [w["error"] for w in json_log.of("log.sink_failed")] == ["OSError"]
    assert [w["error"] for w in json_log.of("tracing.export_failed")] == ["ConnectionError"]


def test_a_failing_sink_keeps_nothing_but_the_stream_keeps_everything(make_client, settings, monkeypatch, json_log):
    # FR-010, FR-015
    _outcome, _calls, api, run = stub_run(make_client, settings, monkeypatch, failing_sink=True)
    assert api.get(f"/api/runs/{run['id']}/log").json()["lines"] == []
    events = [r["event"] for r in json_log() if r.get("run_id") == run["id"]]
    assert events[0] == "run.start" and events[-1] == "run.end"


def test_a_sink_failure_never_prints_a_logging_traceback(make_client, settings, monkeypatch, capfd):  # FR-015
    assert logging.raiseExceptions is True   # the default that makes plain handlers print "--- Logging error ---"
    stub_run(make_client, settings, monkeypatch, failing_sink=True)
    assert "Logging error" not in capfd.readouterr().err


def test_a_line_that_cannot_be_rendered_keeps_its_event_and_the_run_goes_on(make_client, settings, monkeypatch,
                                                                           json_log):  # FR-015
    from kestrel import logging_setup
    working, _calls, _api, _run = stub_run(make_client, settings, monkeypatch)

    def failing(record):
        raise ValueError("cannot render")
    monkeypatch.setattr(logging_setup, "record_fields", failing)
    broken, _calls, _api, run = stub_run(make_client, settings, monkeypatch)
    assert broken == working
    assert json_log.of("log.format_failed") and all(set(r) >= {"ts", "level", "logger", "event"} for r in json_log())


def test_a_failing_span_operation_is_one_warning_and_an_untraced_run(make_client, settings, monkeypatch,
                                                                     span_collector, json_log):  # FR-015
    from kestrel import tracing
    working, _calls, _api, _run = stub_run(make_client, settings, monkeypatch)

    def break_the_sdk_tracer():
        def failing(*args, **kwargs):
            raise RuntimeError("span backend broken")
        monkeypatch.setattr(tracing.current()._tracer, "start_span", failing)
    traced, _calls, _api, _run = stub_run(make_client, settings, monkeypatch, exporter=span_collector,
                                          prepare=break_the_sdk_tracer)
    assert traced == working and list(span_collector.get_finished_spans()) == []
    assert [w["error"] for w in json_log.of("tracing.span_failed")] == ["RuntimeError"]
    assert [r["event"] for r in json_log() if r.get("run_id") == _run["id"]][0] == "run.start"
