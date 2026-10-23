"""Shared fixtures (tasks.md, "Shared conventions")."""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from kestrel.api.main import create_app
from kestrel.settings import Settings


def _settings(tmp_path, mode: str) -> Settings:
    return Settings(mode=mode, db_path=tmp_path / "data" / "kestrel.db",
                    key_file=tmp_path / "keys" / "secret.key", secret_key=None)


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
             judge=None) -> TestClient:
        client = TestClient(create_app(app_settings or settings, transport=transport, resolver=resolver,
                                       library=library, judge=judge))
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
