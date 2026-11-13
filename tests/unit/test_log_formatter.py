"""The `kestrel` stream's rendering: one JSON object per line by default, the same fields as plain text by setting
(010/FR-006), and nothing but allow-listed fields — never an exception's message (010/FR-009)."""
import io
import json
import logging
import re

import pytest

from kestrel import events
from kestrel.logging_setup import TextFormatter

FEATURE = "010"

TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


@pytest.fixture
def text_log():
    """The `kestrel` logger rendered by the TextFormatter, alongside json_log."""
    logger = logging.getLogger("kestrel")
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(TextFormatter())
    level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    yield lambda: buffer.getvalue().splitlines()
    logger.removeHandler(handler)
    logger.setLevel(level)


def _judge_line(**overrides):
    fields = dict(kind="judge", model="google/gemini-3.8-flash", prompt="judge@1", latency_ms=912, ok=True,
                  status=200, attempts=1, prompt_tokens=640, completion_tokens=58, total_tokens=698,
                  verdict="failed")
    fields.update(overrides)
    events.model_request(**fields)


def test_every_record_is_one_json_object_on_one_line(json_log):  # FR-006
    _judge_line(model="a\nmodel\rwith\nbreaks")
    lines = json_log.text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["model"] == "a\nmodel\rwith\nbreaks"   # escaped inside the one line, not broken across lines


def test_common_fields_come_first_then_the_scope_then_the_event_fields(json_log):  # FR-005, FR-006
    with events.bind_experiment(7, "B"), events.run_scope():
        events.run_started(None, run_id=42, target_id=3, mode="adaptive", family="direct_injection")
        events.turn_started(2)
        _judge_line()
    record = json_log.of("model.request")[0]
    keys = list(record)
    assert keys[:4] == ["ts", "level", "logger", "event"]
    assert keys[4:11] == ["run_id", "target_id", "mode", "family", "turn", "experiment_id", "arm"]
    assert keys[11:16] == ["kind", "model", "prompt", "latency_ms", "ok"]
    assert TS.match(record["ts"]) and record["level"] == "INFO" and record["logger"] == "kestrel"


def test_a_record_without_an_event_becomes_a_message_event(json_log):  # FR-006
    logging.getLogger("kestrel").info("A pre-existing free-text line.")
    assert json_log() == [{"ts": json_log()[0]["ts"], "level": "INFO", "logger": "kestrel", "event": "message",
                           "message": "A pre-existing free-text line."}]


def test_an_exception_renders_its_class_and_frames_never_its_message(json_log):  # FR-009
    def boom():
        raise ValueError("http://secret.example/path?token=abc and a provider message")

    try:
        boom()
    except ValueError:
        events.emit("memory.flag_failed", logging.ERROR, exc_info=True)
    record = json_log.of("memory.flag_failed")[0]
    assert record["exc_type"] == "ValueError"
    assert any(re.search(r"test_log_formatter\.py:\d+ in boom$", frame) for frame in record["stack"])
    assert "secret.example" not in json_log.text() and "provider message" not in json_log.text()


def _as_text(value) -> str:
    """The documented text rendering of one value: JSON literals for booleans, null, numbers, lists and objects; a
    string bare unless it holds whitespace, a quote or '=', then JSON-quoted."""
    if isinstance(value, str):
        return json.dumps(value) if re.search(r'[\s"=]', value) or not value else value
    return json.dumps(value, separators=(",", ":"))


def test_the_text_format_renders_the_same_fields(json_log, text_log):  # FR-006
    with events.run_scope():
        events.run_started(None, run_id=42, target_id=3, mode="adaptive", family="direct_injection")
        events.turn_started(2)
        _judge_line()   # no price configured: cost_usd is null and cost_note is text with spaces
    record = json_log.of("model.request")[0]
    line = next(text for text in text_log() if " model.request " in text)
    assert line.startswith(f"{record['ts']} INFO model.request ")
    assert record["cost_usd"] is None and " " in record["cost_note"]
    for key, value in record.items():
        if key not in ("ts", "level", "event", "logger"):
            assert f" {key}={_as_text(value)}" in line, key


def test_the_text_format_quotes_text_with_spaces_and_renders_lists_as_json(text_log):  # FR-006
    events.emit("memory.retrieval", turn=2, warm=True, pattern_count=2, memory_count=0,
                pattern_ids=["pattern:lib:dir-001", "pattern:run:9"])
    events.emit("message", message="Closed run(s) that were interrupted.", count=2)
    lines = text_log()
    assert 'pattern_ids=["pattern:lib:dir-001","pattern:run:9"]' in lines[0]
    assert 'message="Closed run(s) that were interrupted." count=2' in lines[1]


def test_a_field_outside_the_catalogue_is_dropped_and_reported_once_per_name(json_log):  # FR-009
    events.emit("connection.test", latency_ms=5, ok=True, status=200, step="success", url="http://x.test/")
    events.emit("connection.test", latency_ms=6, ok=True, status=200, step="success", url="http://y.test/")
    tests = json_log.of("connection.test")
    assert len(tests) == 2 and all("url" not in record for record in tests)
    warnings = json_log.of("log.unknown_field")
    assert len(warnings) == 1 and warnings[0]["field"] == "url" and warnings[0]["for_event"] == "connection.test"
    assert warnings[0]["level"] == "WARNING" and "x.test" not in json_log.text()


def test_a_constant_message_stays_the_record_message_for_other_handlers(json_log, caplog):  # FR-006
    caplog.set_level(logging.ERROR, logger="kestrel")
    events.emit("key.mismatch", logging.ERROR, message="The encryption key doesn't match the saved one.")
    assert "doesn't match" in caplog.text
    record = json_log.of("key.mismatch")[0]
    assert record["level"] == "ERROR" and record["message"] == "The encryption key doesn't match the saved one."


def test_a_record_that_cannot_be_rendered_keeps_its_event_and_warns_once(json_log):  # FR-015
    class Unprintable:
        def __str__(self):
            raise RuntimeError("cannot render")

        __repr__ = __str__

    events.emit("message", message="constant text", path=Unprintable())
    events.emit("message", message="constant text", path=Unprintable())
    records = json_log()
    assert [r["event"] for r in records].count("message") == 2
    assert all("path" not in r for r in records)
    failed = [r for r in records if r["event"] == "log.format_failed"]
    assert len(failed) == 1 and failed[0]["error"] == "RuntimeError" and failed[0]["for_event"] == "message"


def test_the_stream_stops_at_kestrels_own_handlers(settings, monkeypatch):  # FR-009 (defence in depth)
    """A root handler configured outside Kestrel (uvicorn --log-config, logging.basicConfig) would render a record's
    exception with its message; configure_logging makes the `kestrel` logger stop at its own handlers."""
    from kestrel.logging_setup import configure_logging
    kestrel = logging.getLogger("kestrel")
    monkeypatch.setattr(kestrel, "propagate", True)   # as an unconfigured logger starts
    handlers, level = list(kestrel.handlers), kestrel.level
    seen = []

    class Probe(logging.Handler):
        def emit(self, record):
            seen.append(record)

    probe, root = Probe(), logging.getLogger()
    root.addHandler(probe)
    try:
        configure_logging(settings)
        try:
            raise ValueError("an exception message that must not be rendered")
        except ValueError:
            events.emit("memory.flag_failed", logging.ERROR, exc_info=True)
    finally:   # leave the logger as found: a later test's own run log handler must be the only one on it
        root.removeHandler(probe)
        for installed in [h for h in kestrel.handlers if h not in handlers]:
            kestrel.removeHandler(installed)
        kestrel.setLevel(level)
    assert kestrel.propagate is False and seen == []
