"""Optional OpenTelemetry tracing (feature 010): one trace per run behind KESTREL_TRACING (contracts/tracing.md).

This module has no module-level import of any tracing package (FR-014): with the flag off — the default — the no-op
tracer is all there is, and nothing from the tracing packages is imported. With it on, `configure_tracing` imports the
SDK and, unless a test injects an exporter, the OTLP/HTTP exporter (the optional `kestrel[otel]` extra); if they are
missing, one `tracing.unavailable` warning and the no-op. The tracer provider is private: never installed as the
global provider, so the web framework's and ChromaDB's own telemetry never see it and nothing but Kestrel's spans
exist. A run's root span starts from an empty context (no parent, whatever the ambient context holds) and every child
names its parent explicitly. A failed or refused delivery is one `tracing.export_failed` warning; shutdown waits at
most `timeout_s` whatever the SDK does (its own flush timeouts are not honoured). No propagator is installed, so no
trace header ever reaches a target (FR-013, FR-015).
"""
from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator

OTEL_EXTRA = "kestrel[otel]"
SERVICE_NAME = "kestrel"


class NoopTracing:
    """The tracer when tracing is off: every operation does nothing, so a run behaves exactly as untraced."""

    enabled = False

    def start_root(self, name: str, **attributes: Any) -> Any:
        return None

    def start_span(self, name: str, *, parent: Any, **attributes: Any) -> Any:
        return None

    def end_span(self, span: Any, **attributes: Any) -> None:
        return None

    @contextmanager
    def span(self, name: str, *, parent: Any, **attributes: Any) -> Iterator[Any]:
        yield None

    def set_attributes(self, span: Any, **attributes: Any) -> None:
        return None

    def force_flush(self, timeout_s: float = 5.0) -> None:
        return None

    def shutdown(self, timeout_s: float = 5.0) -> None:
        return None


def _warn(event: str, key: str, **fields: Any) -> None:
    from kestrel import events   # imported late: events imports this module
    events.warn_once(event, key, **fields)


class OtelTracing:
    """The OpenTelemetry adapter: a private provider, roots from an empty context, explicit parents. A failure in any
    span operation is one `tracing.span_failed` warning per cause and never reaches the run (FR-015)."""

    enabled = True

    def __init__(self, provider: Any, empty_context: Callable[[], Any], with_parent: Callable[[Any, Any], Any]):
        self._provider = provider
        self._tracer = provider.get_tracer("kestrel")
        self._empty_context = empty_context
        self._with_parent = with_parent

    def start_root(self, name: str, **attributes: Any) -> Any:
        try:
            return self._tracer.start_span(name, context=self._empty_context(), attributes=attributes or None)
        except Exception as error:
            _span_failed(error)
            return None

    def start_span(self, name: str, *, parent: Any, **attributes: Any) -> Any:
        if parent is None:
            return None
        try:
            context = self._with_parent(parent, self._empty_context())
            return self._tracer.start_span(name, context=context, attributes=attributes or None)
        except Exception as error:
            _span_failed(error)
            return None

    def end_span(self, span: Any, **attributes: Any) -> None:
        if span is None:
            return
        try:
            if attributes:
                span.set_attributes(attributes)
            span.end()
        except Exception as error:
            _span_failed(error)

    @contextmanager
    def span(self, name: str, *, parent: Any, **attributes: Any) -> Iterator[Any]:
        span = self.start_span(name, parent=parent, **attributes)
        try:
            yield span
        finally:
            self.end_span(span)

    def set_attributes(self, span: Any, **attributes: Any) -> None:
        if span is None or not attributes:
            return
        try:
            span.set_attributes(attributes)
        except Exception as error:
            _span_failed(error)

    def force_flush(self, timeout_s: float = 5.0) -> None:
        """Deliver what is queued, waiting at most `timeout_s` (the SDK's own flush ignores its timeout)."""
        _bounded(self._provider.force_flush, timeout_s)

    def shutdown(self, timeout_s: float = 5.0) -> None:
        """Flush and stop, waiting at most `timeout_s`: the SDK's shutdown can wait 30 s, so it runs in a daemon
        thread joined for the bound; whatever is still undelivered is abandoned with the process. Never raises."""
        _bounded(self._provider.shutdown, timeout_s)


def _span_failed(error: Exception) -> None:
    _warn("tracing.span_failed", type(error).__name__, error=type(error).__name__)


def _bounded(call: Callable[[], Any], timeout_s: float) -> None:
    def run() -> None:
        try:
            call()
        except Exception:
            pass
    thread = threading.Thread(target=run, name="kestrel-tracing", daemon=True)
    thread.start()
    thread.join(timeout_s)


class _GuardedExporter:
    """Wraps the exporter so that an exception and a failure result from `export()` each become the single
    `tracing.export_failed` warning (the SDK logs the first and is silent about the second) — and never raise."""

    def __init__(self, inner: Any, results: Any) -> None:
        self._inner = inner
        self._results = results

    def export(self, spans: Any) -> Any:
        try:
            result = self._inner.export(spans)
        except Exception as error:
            _warn("tracing.export_failed", "export", error=type(error).__name__)
            return self._results.FAILURE
        if result != self._results.SUCCESS:
            _warn("tracing.export_failed", "export", error="failure_result")
        return result

    def shutdown(self) -> None:
        try:
            self._inner.shutdown()
        except Exception:
            pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        try:
            return bool(self._inner.force_flush(timeout_millis))
        except Exception:
            return False


_NOOP = NoopTracing()
_current: Any = _NOOP


def current() -> Any:
    """The configured tracer, or the no-op."""
    return _current


def configure_tracing(settings: Any, *, exporter: Any = None) -> Any:
    """The tracer for this process (called by create_app). Off: the no-op, importing nothing. On: the SDK and — unless
    `exporter` is injected (tests) — the OTLP/HTTP exporter constructed without arguments, so every standard
    `OTEL_EXPORTER_OTLP_*` variable applies unchanged; a missing package is one warning and the no-op."""
    global _current
    previous, _current = _current, _NOOP
    previous.shutdown(1.0)   # a tracer configured earlier in this process (tests), bounded
    if not settings.tracing:
        return _current
    try:
        from opentelemetry import trace
        from opentelemetry.context import Context
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExportResult
        if exporter is None:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter()
    except ImportError:
        _warn("tracing.unavailable", "package_missing", cause="package_missing", extra=OTEL_EXTRA)
        return _current
    except Exception as error:   # e.g. a certificate the OTEL_* variables name cannot be read: never stop start-up
        _warn("tracing.unavailable", "setup_failed", cause="setup_failed", error=type(error).__name__)
        return _current
    try:
        _quiet_sdk_loggers()
        provider = TracerProvider(resource=Resource.create(
            {"service.name": os.environ.get("OTEL_SERVICE_NAME") or SERVICE_NAME}))
        guarded: Any = _GuardedExporter(exporter, SpanExportResult)   # a SpanExporter by duck typing
        provider.add_span_processor(BatchSpanProcessor(guarded))
    except Exception as error:
        _warn("tracing.unavailable", "setup_failed", cause="setup_failed", error=type(error).__name__)
        return _current
    _current = OtelTracing(provider, Context, trace.set_span_in_context)
    return _current


def _quiet_sdk_loggers() -> None:
    """The SDK's own log lines never reach Kestrel's JSON stream, nor logging's last-resort stderr handler: Kestrel's
    guard reports a delivery failure once (contracts/tracing.md)."""
    logger = logging.getLogger("opentelemetry")
    logger.propagate = False
    if not any(isinstance(handler, logging.NullHandler) for handler in logger.handlers):
        logger.addHandler(logging.NullHandler())


def reset() -> None:
    """Back to the no-op (tests); a configured tracer is shut down first, bounded."""
    global _current
    previous, _current = _current, _NOOP
    previous.shutdown(1.0)
