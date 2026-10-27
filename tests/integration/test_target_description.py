"""The optional one-line purpose description on a target (FR-020): saved, returned, editable without a re-test."""
import uuid

import httpx

from kestrel.api.main import load_terms
from tests.support import StubJudge, fixture_library

SECRET = "s3cret-header-value"
CURRENT_TERMS = load_terms().version
REPLY = httpx.MockTransport(lambda r: httpx.Response(200, json={"reply": "ok"}))


def connection(**changes):
    base = {"url": "http://127.0.0.1:8102/chat", "method": "POST",
            "headers": [{"name": "X-API-Key", "value": SECRET}],
            "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    return {**base, **changes}


def _tested_form(api) -> str:
    form_id = str(uuid.uuid4())
    assert api.post("/api/connection-tests", json={"form_id": form_id, "target_id": None, "display_name": "A",
                                                   "settings": connection()}).json()["ok"]
    return form_id


def test_a_target_saves_and_returns_its_description(make_client):
    api = make_client(transport=REPLY, library=fixture_library(), judge=StubJudge())
    form_id = _tested_form(api)
    body = api.post("/api/targets", json={"form_id": form_id, "name": "A", "settings": connection(),
                                          "permission_confirmed": True, "terms_version": CURRENT_TERMS,
                                          "description": "a customs classification assistant"})
    assert body.status_code == 201
    tid = body.json()["id"]
    assert body.json()["description"] == "a customs classification assistant"
    assert api.get(f"/api/targets/{tid}").json()["description"] == "a customs classification assistant"
    assert api.get("/api/targets").json()[0]["description"] == "a customs classification assistant"


def test_a_too_long_description_is_refused(make_client):
    api = make_client(transport=REPLY, library=fixture_library(), judge=StubJudge())
    form_id = _tested_form(api)
    r = api.post("/api/targets", json={"form_id": form_id, "name": "A", "settings": connection(),
                                       "permission_confirmed": True, "terms_version": CURRENT_TERMS,
                                       "description": "x" * 201})
    assert r.status_code == 422
    assert any(e["field"] == "description" for e in r.json()["errors"])


def test_editing_only_the_description_needs_no_new_connection_test(make_client):
    api = make_client(transport=REPLY, library=fixture_library(), judge=StubJudge())
    form_id = _tested_form(api)
    tid = api.post("/api/targets", json={"form_id": form_id, "name": "A", "settings": connection(),
                                         "permission_confirmed": True, "terms_version": CURRENT_TERMS,
                                         "description": "first"}).json()["id"]
    # A fresh form with no successful test; a description-only edit must still be allowed (fingerprint unchanged).
    r = api.put(f"/api/targets/{tid}", json={"form_id": str(uuid.uuid4()), "name": "A", "settings": connection(),
                                             "permission_confirmed": True, "terms_version": CURRENT_TERMS,
                                             "description": "second"})
    assert r.status_code == 200 and r.json()["description"] == "second"
