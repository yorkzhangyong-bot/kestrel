"""Shared setup for the integration tests."""
import pytest


@pytest.fixture(autouse=True)
def _offline_attack_defaults(monkeypatch):
    """Default the feature-002 UI calls to safe offline stubs.

    The screen now calls attack_families() and list_runs() on every render. Feature-001 UI tests don't stub
    them, and without this they would make real network attempts (flaky if anything listens on the API port).
    A test that cares sets its own stub, which wins because monkeypatch applies last.
    """
    import api_client

    monkeypatch.setattr(api_client, "attack_families", lambda: {"library_version": "0", "families": []})
    monkeypatch.setattr(api_client, "list_runs", lambda target_id: [])
