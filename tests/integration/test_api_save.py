"""POST /api/targets and GET /api/targets (contracts/kestrel-api.md)."""
import uuid

import httpx
import pytest

from kestrel.api.main import load_terms

SECRET = "s3cret-header-value"
# The current terms version, from the source of truth, so this suite isn't rewritten on every bump.
CURRENT_TERMS = load_terms().version


def connection(**changes):
    base = {"url": "http://agent.test/chat", "method": "POST", "headers": [{"name": "X-API-Key", "value": SECRET}],
            "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    return {**base, **changes}


def connection_request(form_id, **changes):
    return {"form_id": form_id, "target_id": None, "display_name": "Agent", "settings": connection(**changes)}


def save_request(form_id, name="HS Agent", permission=True, terms=CURRENT_TERMS, **changes):
    return {"form_id": form_id, "name": name, "settings": connection(**changes), "permission_confirmed": permission,
            "terms_version": terms}


def replying_ok():
    return httpx.MockTransport(lambda request: httpx.Response(200, json={"reply": "Hi"}))


def successful_form(client, **changes) -> str:
    """Run a successful test in a new form and return its form_id."""
    form_id = str(uuid.uuid4())
    assert client.post("/api/connection-tests", json=connection_request(form_id, **changes)).json()["ok"]
    return form_id


@pytest.fixture
def api(make_client):
    return make_client(transport=replying_ok())


def error_of(response):
    return response.json()["error"]


def test_saving_after_a_successful_test(api):
    response = api.post("/api/targets", json=save_request(successful_form(api)))
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "HS Agent" and body["url"] == "http://agent.test/chat"
    assert body["headers"] == [{"name": "X-API-Key", "has_value": True, "readable": True}]
    assert body["terms_version"] == CURRENT_TERMS and body["permission_confirmed_at"]
    assert SECRET not in response.text


def test_saving_without_a_test_is_refused(api):
    response = api.post("/api/targets", json=save_request(str(uuid.uuid4())))
    assert response.status_code == 409
    assert error_of(response)["code"] == "not_tested"


def test_saving_after_the_most_recent_test_failed_is_refused(make_client):
    answers = iter([httpx.Response(200, json={"reply": "Hi"}), httpx.Response(500, json={})])
    client = make_client(transport=httpx.MockTransport(lambda request: next(answers)))
    form_id = successful_form(client)
    assert client.post("/api/connection-tests", json=connection_request(form_id)).json()["ok"] is False
    response = client.post("/api/targets", json=save_request(form_id))
    assert response.status_code == 409 and error_of(response)["code"] == "not_tested"


def test_saving_settings_that_changed_after_the_test_is_refused(api):
    response = api.post("/api/targets", json=save_request(successful_form(api), response_path="$.other"))
    assert response.status_code == 409 and error_of(response)["code"] == "not_tested"


def test_a_different_display_name_alone_still_saves(api):
    assert api.post("/api/targets", json=save_request(successful_form(api), name="Another name")).status_code == 201


def test_the_permission_must_be_confirmed(api):
    response = api.post("/api/targets", json=save_request(successful_form(api), permission=False))
    assert response.status_code == 422
    assert "permission_confirmed" in [e["field"] for e in response.json()["errors"]]


def test_the_terms_version_must_be_current(api):
    response = api.post("/api/targets", json=save_request(successful_form(api), terms="0"))
    assert response.status_code == 422
    assert "terms_version" in [e["field"] for e in response.json()["errors"]]


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_a_display_name_of_1_to_100_characters_is_required_to_save(api, name):
    response = api.post("/api/targets", json=save_request(successful_form(api), name=name))
    assert response.status_code == 422
    assert "name" in [e["field"] for e in response.json()["errors"]]


def test_names_are_unique_ignoring_case(api):
    assert api.post("/api/targets", json=save_request(successful_form(api), name="HS Agent")).status_code == 201
    response = api.post("/api/targets", json=save_request(successful_form(api), name="hs agent"))
    assert response.status_code == 409
    assert error_of(response)["code"] == "name_taken" and error_of(response)["field"] == "name"


def test_saved_targets_are_listed_and_survive_a_restart(make_client, settings):
    client = make_client(transport=replying_ok())
    client.post("/api/targets", json=save_request(successful_form(client)))
    listed = client.get("/api/targets").json()
    assert [t["name"] for t in listed] == ["HS Agent"]
    assert listed[0]["permission_confirmed_at"] and listed[0]["terms_version"] == CURRENT_TERMS
    assert make_client(settings).get("/api/targets").json() == listed


def test_config_includes_the_terms(client):
    terms = client.get("/api/config").json()["terms"]
    assert terms["version"] == CURRENT_TERMS
    assert "written permission" in terms["text"]


def test_the_saved_header_value_never_appears_in_logs_or_responses(api, all_logs):
    responses = []
    form_id = str(uuid.uuid4())
    responses.append(api.post("/api/connection-tests", json=connection_request(form_id)))
    responses.append(api.post("/api/targets", json=save_request(form_id)))
    responses.append(api.post("/api/targets", json=save_request(form_id)))  # name taken
    responses.append(api.get("/api/targets"))
    responses.append(api.post("/api/targets", json=save_request(str(uuid.uuid4()), name="Other")))  # not tested
    assert all(SECRET not in response.text for response in responses)
    assert all_logs().count(SECRET) == 0
