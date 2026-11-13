"""Shared fixtures (tasks.md, "Shared conventions")."""
from __future__ import annotations

import io
import json
import logging
import os
import sys

import pytest
from fastapi.testclient import TestClient

from kestrel.api.main import create_app
from kestrel.experience.store import ExperienceStore
from kestrel.settings import Settings
from tests.support import ModelTransport, StubEmbeddingFunction

# Feature 010, SC-007: with KESTREL_TEST_BLOCK_OTLP=1 the OTLP/HTTP exporter cannot be imported for the whole session
# (as if the optional `otel` extra were absent) and the tests that need the real exporter are skipped.
OTLP_EXPORTER_MODULE = "opentelemetry.exporter.otlp.proto.http.trace_exporter"
BLOCK_OTLP = os.environ.get("KESTREL_TEST_BLOCK_OTLP") == "1"
if BLOCK_OTLP:
    sys.modules[OTLP_EXPORTER_MODULE] = None  # type: ignore[assignment]

# Feature 010: configure_logging makes the `kestrel` logger stop at its own handlers (no propagation to the root).
# pytest attaches its capture handler (caplog, the report's captured log) to non-propagating loggers only when a
# test phase starts — it misses a logger that *becomes* non-propagating mid-test — so the logger is non-propagating
# from the start of the session, as it is in production once the app is built, and every test captures it alike.
logging.getLogger("kestrel").propagate = False


def pytest_collection_modifyitems(config, items):
    if not BLOCK_OTLP:
        return
    skip = pytest.mark.skip(reason="KESTREL_TEST_BLOCK_OTLP=1 blocks the OTLP/HTTP exporter import (010/SC-007)")
    for item in items:
        if "real_otlp_exporter" in item.keywords:
            item.add_marker(skip)


def _settings(tmp_path, mode: str) -> Settings:
    return Settings(mode=mode, db_path=tmp_path / "data" / "kestrel.db",
                    key_file=tmp_path / "keys" / "secret.key", secret_key=None,
                    chroma_path=tmp_path / "data" / "chroma")


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Local mode, with the database and key file under tmp_path."""
    return _settings(tmp_path, "local")


@pytest.fixture
def hosted_settings(tmp_path) -> Settings:
    return _settings(tmp_path, "hosted")


@pytest.fixture
def make_client(settings):
    """Build a TestClient over create_app; tests can pass an httpx.MockTransport and a fake resolver."""
    clients = []

    def make(app_settings: Settings | None = None, *, transport=None, resolver=None, library=None,
             judge=None, attacker=None, experience=None, span_exporter=None) -> TestClient:
        app_settings = app_settings or settings
        # Inject a stub-backed experience store so API tests stay offline (no embedding-model download, R2).
        if experience is None:
            experience = ExperienceStore(app_settings.chroma_path, embedding_function=StubEmbeddingFunction())
        kwargs = {} if span_exporter is None else {"span_exporter": span_exporter}
        client = TestClient(create_app(app_settings, transport=transport, resolver=resolver,
                                       library=library, judge=judge, attacker=attacker, experience=experience,
                                       **kwargs))
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@pytest.fixture
def all_logs(caplog):
    """Return a function giving every log line captured so far as one string."""
    caplog.set_level(logging.DEBUG)
    return lambda: caplog.text


@pytest.fixture(autouse=True)
def _release_chroma():
    """Each test opens its own ChromaDB store under tmp; release the cached clients so file handles don't pile up."""
    yield
    try:
        from chromadb.api.shared_system_client import SharedSystemClient
        SharedSystemClient.clear_system_cache()
    except Exception:
        pass


# ---- feature 010: the structured log stream, spans and the offline model transport (tasks.md T003) ----


class JsonLog:
    """The `kestrel` stream as the real JsonFormatter renders it: `json_log()` parses every line written so far (one
    JSON object per line, in order — a line that does not parse fails the test), `json_log.text()` is the raw text
    for counting secrets, and `json_log.of(event)` filters by event name."""

    def __init__(self, buffer: io.StringIO) -> None:
        self._buffer = buffer

    def text(self) -> str:
        return self._buffer.getvalue()

    def __call__(self) -> list[dict]:
        return [json.loads(line) for line in self.text().splitlines() if line.strip()]

    def of(self, event: str) -> list[dict]:
        return [record for record in self() if record.get("event") == event]

    def events(self) -> list[str]:
        return [record["event"] for record in self()]


@pytest.fixture
def json_log():
    """Attach the real JsonFormatter (kestrel.logging_setup) to a StringIO handler on the `kestrel` logger."""
    from kestrel.logging_setup import JsonFormatter
    logger = logging.getLogger("kestrel")
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JsonFormatter())
    previous = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    yield JsonLog(buffer)
    logger.removeHandler(handler)
    logger.setLevel(previous)


@pytest.fixture
def span_collector():
    """The SDK's in-process span exporter; hand it to create_app(span_exporter=...) or configure_tracing(exporter=...)
    and read `get_finished_spans()` after `tracing.current().force_flush()`."""
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    return InMemorySpanExporter()


@pytest.fixture
def model_transport() -> ModelTransport:
    """One offline transport for the stub target and the real attacker/judge/recommender clients (research D10)."""
    return ModelTransport()


@pytest.fixture(autouse=True)
def _reset_observability():
    """The tracer, the price table, the warn-once sets and the `kestrel` logger's handlers are module-level (feature
    010); reset them after every test so one test's tracing, prices or app logging never leak into the next (an app's
    run log handler left on the logger would keep a later test's records twice). A module never imported holds no
    state to reset."""
    yield
    tracing = sys.modules.get("kestrel.tracing")
    if tracing is not None:
        tracing.reset()
    events = sys.modules.get("kestrel.events")
    if events is not None:
        events.reset()
    logging_setup = sys.modules.get("kestrel.logging_setup")
    if logging_setup is not None:
        logging_setup.reset()


@pytest.fixture(autouse=True)
def _offline_run_log(request, monkeypatch):
    """The screen fetches an opened run's log (feature 010); UI tests that do not stub it would otherwise call a real
    API on 127.0.0.1:8000. Default to an empty log offline; the viewer tests stub their own and
    `tests/unit/test_api_client_run_log.py` puts the real client back. e2e tests use the real API. Not
    `raising=False`: a renamed or removed client function fails here instead of being masked."""
    if request.node.get_closest_marker("e2e"):
        return
    import api_client
    monkeypatch.setattr(api_client, "get_run_log", lambda run_id: {"run_id": run_id, "lines": [], "kept": 0,
                                                                   "dropped": 0, "truncated": False})
