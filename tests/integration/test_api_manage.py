"""GET, PUT and DELETE /api/targets/{id}, re-testing with target_id, and key loss (contracts/kestrel-api.md)."""
import uuid

import httpx
import pytest

from kestrel.api.main import load_terms
from kestrel.settings import Settings

SECRET = "s3cret-header-value"
CURRENT_TERMS = load_terms().version


def connection(**changes):
    base = {"url": "http://agent.test/chat", "method": "POST", "headers": [{"name": "X-API-Key", "value": SECRET}],
            "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    return {**base, **changes}


def check(client, form_id, target_id=None, **changes):
    return client.post("/api/connection-tests", json={"form_id": form_id, "target_id": target_id,
                                                      "display_name": "Agent", "settings": connection(**changes)})


def save_body(form_id, name="HS Agent", **changes):
    return {"form_id": form_id, "name": name, "settings": connection(**changes), "permission_confirmed": True,
            "terms_version": CURRENT_TERMS}


class Recorder:
    """A MockTransport that answers {"reply": "Hi"} and remembers what it received."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request):
        self.requests.append(request)
        return httpx.Response(200, json={"reply": "Hi"})


@pytest.fixture
def recorder():
    return Recorder()


@pytest.fixture
def api(make_client, recorder):
    return make_client(transport=recorder.transport)


def saved_target(client) -> dict:
    form_id = str(uuid.uuid4())
    assert check(client, form_id).json()["ok"]
    response = client.post("/api/targets", json=save_body(form_id))
    assert response.status_code == 201
    return response.json()


KEPT = [{"name": "X-API-Key", "value": None}]


def test_get_shows_header_names_without_values(api):
    target = saved_target(api)
    response = api.get(f"/api/targets/{target['id']}")
    assert response.status_code == 200
    assert response.json()["headers"] == [{"name": "X-API-Key", "has_value": True, "readable": True}]
    assert SECRET not in response.text


def test_a_name_only_change_saves_without_a_test(api):
    target = saved_target(api)
    response = api.put(f"/api/targets/{target['id']}", json=save_body(str(uuid.uuid4()), name="Renamed", headers=KEPT))
    assert response.status_code == 200 and response.json()["name"] == "Renamed"


def test_changed_settings_without_a_matching_test_are_refused(api):
    target = saved_target(api)
    response = api.put(f"/api/targets/{target['id']}",
                       json=save_body(str(uuid.uuid4()), headers=KEPT, response_path="$.other"))
    assert response.status_code == 409 and response.json()["error"]["code"] == "not_tested"


def test_a_retest_with_target_id_sends_the_stored_value_and_put_keeps_it(api, recorder):
    target = saved_target(api)
    recorder.requests.clear()
    form_id = str(uuid.uuid4())
    assert check(api, form_id, target_id=target["id"], headers=KEPT, response_path="$.reply").json()["ok"]
    assert recorder.requests[-1].headers["x-api-key"] == SECRET
    response = api.put(f"/api/targets/{target['id']}", json=save_body(form_id, headers=KEPT))
    assert response.status_code == 200
    recorder.requests.clear()
    assert check(api, str(uuid.uuid4()), target_id=target["id"], headers=KEPT).json()["ok"]
    assert recorder.requests[-1].headers["x-api-key"] == SECRET


def test_a_kept_value_for_a_header_that_isnt_stored_is_refused(api):
    target = saved_target(api)
    response = check(api, str(uuid.uuid4()), target_id=target["id"], headers=[{"name": "X-Unknown", "value": None}])
    assert response.status_code == 422
    assert "settings.headers.0.value" in [e["field"] for e in response.json()["errors"]]


def test_a_new_url_renews_the_permission_date(api):
    target = saved_target(api)
    form_id = str(uuid.uuid4())
    new_url = "http://agent.test/v2/chat"
    assert check(api, form_id, target_id=target["id"], headers=KEPT, url=new_url).json()["ok"]
    response = api.put(f"/api/targets/{target['id']}", json=save_body(form_id, headers=KEPT, url=new_url))
    assert response.status_code == 200
    assert response.json()["url"] == new_url
    assert response.json()["permission_confirmed_at"] >= target["permission_confirmed_at"]


def test_delete_then_get_is_404(api):
    target = saved_target(api)
    assert api.delete(f"/api/targets/{target['id']}").status_code == 204
    assert api.get(f"/api/targets/{target['id']}").status_code == 404
    assert api.get("/api/targets").json() == []


def test_an_unknown_id_is_404_everywhere(api):
    assert api.get("/api/targets/999").status_code == 404
    assert api.put("/api/targets/999", json=save_body(str(uuid.uuid4()))).status_code == 404
    assert api.delete("/api/targets/999").status_code == 404
    assert check(api, str(uuid.uuid4()), target_id=999, headers=KEPT).status_code == 404


def test_key_loss_makes_headers_unreadable_until_they_are_re_entered(make_client, settings, recorder, tmp_path,
                                                                      all_logs):
    target = saved_target(make_client(transport=recorder.transport))
    other_key = Settings(mode="local", db_path=settings.db_path, key_file=tmp_path / "other.key", secret_key=None)
    client = make_client(other_key, transport=recorder.transport)

    assert "doesn't match" in all_logs()
    assert client.get(f"/api/targets/{target['id']}").json()["headers"][0]["readable"] is False

    recorder.requests.clear()
    result = check(client, str(uuid.uuid4()), target_id=target["id"], headers=KEPT).json()
    assert result["step"] == "credentials_unreadable" and result["ok"] is False
    assert recorder.requests == []

    form_id = str(uuid.uuid4())
    new_value = "re-entered-value-123"
    assert check(client, form_id, target_id=target["id"],
                 headers=[{"name": "X-API-Key", "value": new_value}]).json()["ok"]
    response = client.put(f"/api/targets/{target['id']}",
                          json=save_body(form_id, headers=[{"name": "X-API-Key", "value": new_value}]))
    assert response.status_code == 200
    assert response.json()["headers"][0]["readable"] is True
    assert all_logs().count(SECRET) == 0 and all_logs().count(new_value) == 0
