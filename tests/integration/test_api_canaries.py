"""Canaries on the target endpoints (contracts/kestrel-api.md, FR-024, FR-025)."""
import uuid

import httpx
import pytest

from kestrel.api.main import load_terms

FEATURE = "002"

SECRET = "s3cret-header-value"
CURRENT_TERMS = load_terms().version
CANARY = "KESTREL-CANARY-7Q4M2X"


def connection(**changes):
    base = {"url": "http://agent.test/chat", "method": "POST", "headers": [{"name": "X-API-Key", "value": SECRET}],
            "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    return {**base, **changes}


def successful_form(client, **changes) -> str:
    form_id = str(uuid.uuid4())
    body = {"form_id": form_id, "target_id": None, "display_name": "Agent", "settings": connection(**changes)}
    assert client.post("/api/connection-tests", json=body).json()["ok"]
    return form_id


def save_body(form_id, **extra):
    return {"form_id": form_id, "name": "HS Agent", "settings": connection(), "permission_confirmed": True,
            "terms_version": CURRENT_TERMS, **extra}


@pytest.fixture
def api(make_client):
    return make_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"reply": "Hi"})))


def save_with_canaries(api, canaries):
    return api.post("/api/targets", json=save_body(successful_form(api), canaries=canaries))


def test_canaries_save_and_read_back_in_full(api):
    """Not a credential, so returned whole, unlike an auth header value (R7)."""
    created = save_with_canaries(api, [CANARY, "SECOND-CANARY-VALUE"])
    assert created.status_code == 201
    assert created.json()["canaries"] == [CANARY, "SECOND-CANARY-VALUE"]
    fetched = api.get(f"/api/targets/{created.json()['id']}").json()
    assert fetched["canaries"] == [CANARY, "SECOND-CANARY-VALUE"]


def test_a_target_saved_without_canaries_has_none(api):
    created = api.post("/api/targets", json=save_body(successful_form(api)))
    assert created.json()["canaries"] == []


@pytest.mark.parametrize("bad", ["", "short", "1234567"])
def test_a_canary_under_8_characters_is_422(api, bad):
    response = save_with_canaries(api, [bad])
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "canaries.0"


def test_a_duplicate_canary_is_422(api):
    response = save_with_canaries(api, [CANARY, CANARY])
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "canaries.1"


def test_a_short_canary_is_not_saved(api):
    save_with_canaries(api, ["short"])
    assert api.get("/api/targets").json() == []  # the whole save was rejected


def test_put_without_canaries_keeps_the_stored_ones(api):
    created = save_with_canaries(api, [CANARY]).json()
    form_id = successful_form(api)
    # A PUT that omits canaries leaves them untouched (contracts/kestrel-api.md).
    body = {"form_id": form_id, "name": "Renamed", "settings": connection(headers=[{"name": "X-API-Key",
            "value": None}]), "permission_confirmed": True, "terms_version": CURRENT_TERMS}
    updated = api.put(f"/api/targets/{created['id']}", json=body)
    assert updated.status_code == 200 and updated.json()["canaries"] == [CANARY]


def test_put_with_empty_list_clears_them(api):
    created = save_with_canaries(api, [CANARY]).json()
    form_id = successful_form(api)
    body = {"form_id": form_id, "name": "HS Agent", "settings": connection(headers=[{"name": "X-API-Key",
            "value": None}]), "permission_confirmed": True, "terms_version": CURRENT_TERMS, "canaries": []}
    updated = api.put(f"/api/targets/{created['id']}", json=body)
    assert updated.status_code == 200 and updated.json()["canaries"] == []


def test_changing_canaries_needs_no_new_connection_test(api):
    """Canaries play no part in reaching the agent, so FR-012's retest rule does not apply to them."""
    created = save_with_canaries(api, [CANARY]).json()
    # A fresh form_id with no test recorded; a canary-only change must still save.
    body = {"form_id": str(uuid.uuid4()), "name": "HS Agent", "settings": connection(headers=[{"name": "X-API-Key",
            "value": None}]), "permission_confirmed": True, "terms_version": CURRENT_TERMS,
            "canaries": [CANARY, "ADDED-CANARY-VALUE"]}
    updated = api.put(f"/api/targets/{created['id']}", json=body)
    assert updated.status_code == 200 and updated.json()["canaries"] == [CANARY, "ADDED-CANARY-VALUE"]
