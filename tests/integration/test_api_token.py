"""Hosted mode requires a matching X-Kestrel-Token; local mode is open (Principle IV hardening, item 5).

A fresh clone defaults to hosted (unset mode is hosted), so hosted is fail-closed: without a configured token, or
with a missing/wrong one, every request is refused — the owner must set KESTREL_API_TOKEN or KESTREL_MODE=local.
"""
import dataclasses

from kestrel.settings import Settings

FEATURE = "001"
# Also traces feature 008 (hardening): 008/FR-011 (hosted token, fail-closed), 008/FR-012 (local open, never logged), 008/FR-013 (UI sends it).

TOKEN = "s3cret-hosted-token"


def _hosted(settings: Settings, *, token: str | None = TOKEN) -> Settings:
    return dataclasses.replace(settings, mode="hosted", api_token=token)


def test_local_mode_needs_no_token(client):
    assert client.get("/api/config").status_code == 200


def test_hosted_mode_rejects_a_request_with_no_token(make_client, settings):
    response = make_client(_hosted(settings)).get("/api/config")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_hosted_mode_rejects_a_wrong_token(make_client, settings):
    assert make_client(_hosted(settings)).get("/api/config", headers={"X-Kestrel-Token": "wrong"}).status_code == 401


def test_hosted_mode_accepts_the_right_token(make_client, settings):
    response = make_client(_hosted(settings)).get("/api/config", headers={"X-Kestrel-Token": TOKEN})
    assert response.status_code == 200


def test_hosted_with_no_token_configured_is_fail_closed(make_client, settings):
    response = make_client(_hosted(settings, token=None)).get("/api/config", headers={"X-Kestrel-Token": "anything"})
    assert response.status_code == 401
