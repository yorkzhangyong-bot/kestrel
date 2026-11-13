"""Optional OpenTelemetry tracing (feature 010): one trace per run behind KESTREL_TRACING (contracts/tracing.md).

This module has no module-level import of any tracing package (FR-014). With the flag off — the default — the no-op
tracer below is all there is: it imports nothing and records nothing.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


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


_NOOP = NoopTracing()
_current: Any = _NOOP


def current() -> Any:
    """The configured tracer, or the no-op."""
    return _current


def reset() -> None:
    """Back to the no-op (tests); a configured tracer is shut down first, bounded."""
    global _current
    previous, _current = _current, _NOOP
    previous.shutdown(1.0)
