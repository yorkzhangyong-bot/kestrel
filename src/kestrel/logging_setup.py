"""The `kestrel` log stream (feature 010): JSON Lines by default, the same fields as plain text by setting (research D2).

The stream is the output of the `kestrel` logger and its children on standard error; the web server's own lines are
not part of it. Every record renders as its common fields (`ts`, `level`, `logger`, `event`), then the run's scope,
then the event's own fields; a record logged without an event (a free-text line) becomes a `message` event; an
exception renders as its class (`exc_type`) and frames (`stack`) — never its message (FR-006, FR-009). A record that
cannot be rendered in full keeps its common fields and is reported once (FR-015).
"""
from __future__ import annotations

import json
import logging
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import PurePath
from typing import Any

from kestrel import events

_NEEDS_QUOTES = re.compile(r'[\s"=]')


def timestamp(created: float) -> str:
    """ISO-8601 UTC with milliseconds and a `Z`."""
    moment = datetime.fromtimestamp(created, timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def record_fields(record: logging.LogRecord) -> dict[str, Any]:
    """The record as ordered fields: common, then scope (in SCOPE_FIELDS order), then the event's own, then the
    exception's class and frames."""
    event = getattr(record, "kestrel_event", None)
    fields = dict(getattr(record, "kestrel_fields", None) or {})
    if event is None:   # a line logged without an event: its message, nothing interpolated beyond what it carries
        fields = {"message": record.getMessage()}
    out: dict[str, Any] = {"ts": timestamp(record.created), "level": record.levelname, "logger": record.name,
                           "event": event or "message"}
    for name in events.SCOPE_FIELDS:
        if name in fields:
            out[name] = fields.pop(name)
    out.update(fields)
    if record.exc_info and record.exc_info[0] is not None:
        out["exc_type"] = record.exc_info[0].__name__
        out["stack"] = [f"{_frame_file(frame.filename)}:{frame.lineno} in {frame.name}"
                        for frame in traceback.extract_tb(record.exc_info[2])]
    return out


def _frame_file(filename: str) -> str:
    """The last two parts of a frame's path (`judge/client.py`): enough to find it, no machine-specific prefix."""
    return "/".join(PurePath(filename).parts[-2:])


def _common(record: logging.LogRecord) -> dict[str, Any]:
    return {"ts": timestamp(record.created), "level": record.levelname, "logger": record.name,
            "event": getattr(record, "kestrel_event", None) or "message"}


def _render_failed(record: logging.LogRecord, error: Exception) -> None:
    events.warn_once("log.format_failed", type(error).__name__, error=type(error).__name__,
                     for_event=getattr(record, "kestrel_event", None) or "message")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class JsonFormatter(logging.Formatter):
    """One JSON object per line (JSON Lines), keys in the stable order of `record_fields`."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            return _json(record_fields(record))
        except Exception as error:
            _render_failed(record, error)
            return _json(_common(record))


def _text(value: Any) -> str:
    """A value as text: a string bare unless it holds whitespace, a quote or '=', otherwise a JSON literal."""
    if isinstance(value, str):
        return _json(value) if not value or _NEEDS_QUOTES.search(value) else value
    return _json(value)


class TextFormatter(logging.Formatter):
    """`ts level event key=value …` — the same fields as the JSON line, for reading locally (KESTREL_LOG_FORMAT=text).
    The logger is shown only when it is not `kestrel` itself."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            fields = record_fields(record)
        except Exception as error:
            _render_failed(record, error)
            fields = _common(record)
        try:
            head = [fields.pop("ts"), fields.pop("level"), fields.pop("event")]
            logger = fields.pop("logger")
            if logger != "kestrel":
                head.append(f"logger={logger}")
            return " ".join(head + [f"{name}={_text(value)}" for name, value in fields.items()])
        except Exception as error:
            _render_failed(record, error)
            common = _common(record)
            return f"{common['ts']} {common['level']} {common['event']}"


class _StderrHandler(logging.StreamHandler):
    """Writes to whatever `sys.stderr` is when a record is emitted (as logging's own last-resort handler does)."""

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    @property
    def stream(self):  # type: ignore[override]
        return sys.stderr

    @stream.setter
    def stream(self, value) -> None:
        pass

    def handleError(self, record: logging.LogRecord) -> None:
        """A broken standard error cannot report its own failure; never let it reach the caller (FR-015)."""


def configure_logging(settings: Any) -> logging.Logger:
    """Install the stream on the `kestrel` logger with the chosen format (idempotent: one stream handler however
    often it is called), and forget earlier warnings so each configured logger warns once per cause."""
    logger = logging.getLogger("kestrel")
    logger.setLevel(logging.INFO)
    stream = next((h for h in logger.handlers if isinstance(h, _StderrHandler)), None)
    if stream is None:
        stream = _StderrHandler()
        logger.addHandler(stream)
    stream.setFormatter(TextFormatter() if settings.log_format == "text" else JsonFormatter())
    events.clear_warnings()
    return logger
