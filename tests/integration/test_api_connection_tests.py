"""POST /api/connection-tests (contracts/kestrel-api.md), with httpx.MockTransport standing in for targets."""
import uuid

import httpx
import pytest

SECRET = "s3cret-header-value"
URL_CREDENTIALS = "put credentials in an auth header, not the URL"
RESULT_KEYS = {"ok", "step", "message", "detail", "status_code", "reply_text", "reply_truncated", "duration_ms"}


def payload(display_name="Agent", target_id=None, **settings):
    base = {"url": "http://agent.test/chat", "method": "POST", "headers": [{"name": "X-API-Key", "value": SECRET}],
            "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    return {"form_id": str(uuid.uuid4()), "target_id": target_id, "display_name": display_name,
            "settings": {**base, **settings}}


def replying(body, status=200, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body)
    return httpx.MockTransport(handler)


def test_a_successful_test(make_client):
    client = make_client(transport=replying({"reply": "Hi there"}))
    response = client.post("/api/connection-tests", json=payload())
    assert response.status_code == 200
    body = response.json()
    assert set(body) == RESULT_KEYS
    assert body["ok"] is True and body["step"] == "success" and body["reply_text"] == "Hi there"


@pytest.mark.parametrize("status, step", [(401, "auth_rejected"), (500, "endpoint_error")])
def test_failure_steps_come_back_as_200_results(make_client, status, step):
    client = make_client(transport=replying({"error": "x"}, status=status))
    body = client.post("/api/connection-tests", json=payload()).json()
    assert body["ok"] is False and body["step"] == step


def test_non_json_is_a_result_too(make_client):
    client = make_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"<html>")))
    assert client.post("/api/connection-tests", json=payload()).json()["step"] == "non_json"


@pytest.mark.parametrize("overrides, field", [
    ({"url": ""}, "settings.url"),
    ({"url": "ftp://agent.test/chat"}, "settings.url"),
    ({"body_template": '{"m": 1}'}, "settings.body_template"),
    ({"response_path": ""}, "settings.response_path"),
    ({"response_path": "reply"}, "settings.response_path"),
    ({"headers": [{"name": "Bad Name", "value": SECRET}]}, "settings.headers.0.name"),
    ({"headers": [{"name": "Host", "value": SECRET}]}, "settings.headers.0.name"),
])
def test_invalid_forms_name_the_field_and_never_the_values(make_client, overrides, field):
    seen = []
    client = make_client(transport=replying({"reply": "x"}, seen=seen))
    response = client.post("/api/connection-tests", json=payload(**overrides))
    assert response.status_code == 422
    assert field in [error["field"] for error in response.json()["errors"]]
    assert SECRET not in response.text
    assert seen == []


@pytest.mark.parametrize("url", ["http://user:pass@agent.test/chat", "http://agent.test/chat?api_key=abc123",
                                 "http://agent.test/chat?client_secret=abc123", "http://agent.test/chat?code=abc123",
                                 "http://agent.test/chat?sig=abc123"])
def test_urls_that_carry_credentials_are_refused(make_client, url):
    response = make_client(transport=replying({"reply": "x"})).post("/api/connection-tests", json=payload(url=url))
    assert response.status_code == 422
    assert {"field": "settings.url", "message": URL_CREDENTIALS} in response.json()["errors"]


def test_a_harmless_query_parameter_is_accepted(make_client):
    client = make_client(transport=replying({"reply": "x"}))
    assert client.post("/api/connection-tests", json=payload(url="http://agent.test/chat?keyword=x")).status_code == 200


@pytest.mark.parametrize("value", ["", "abc"])
def test_header_values_shorter_than_4_characters_are_refused(make_client, value):
    response = make_client().post("/api/connection-tests",
                                  json=payload(headers=[{"name": "X-API-Key", "value": value}]))
    assert response.status_code == 422
    assert "settings.headers.0.value" in [error["field"] for error in response.json()["errors"]]


def test_a_kept_value_without_a_target_is_refused(make_client):
    response = make_client().post("/api/connection-tests", json=payload(headers=[{"name": "X-API-Key", "value": None}]))
    assert response.status_code == 422
    assert "settings.headers.0.value" in [error["field"] for error in response.json()["errors"]]


def test_a_test_needs_no_display_name(make_client):
    client = make_client(transport=replying({"reply": "x"}))
    assert client.post("/api/connection-tests", json=payload(display_name="")).status_code == 200


def test_a_second_test_for_the_same_form_gets_409(make_client):
    client = make_client(transport=replying({"reply": "x"}))
    body = payload()
    client.app.state.sessions.start(body["form_id"])
    response = client.post("/api/connection-tests", json=body)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "test_in_progress"


def test_hosted_mode_refuses_a_name_that_resolves_to_a_private_address(make_client, hosted_settings):
    seen = []
    client = make_client(hosted_settings, transport=replying({"reply": "x"}, seen=seen), resolver=lambda host: ["10.0.0.5"])
    body = client.post("/api/connection-tests", json=payload(url="http://internal.example/chat")).json()
    assert body["step"] == "address_not_allowed"
    assert seen == []


def test_an_unknown_target_id_is_404(make_client):
    response = make_client().post("/api/connection-tests", json=payload(target_id=7))
    assert response.status_code == 404


def test_the_header_value_never_reaches_the_logs(make_client, all_logs):
    client = make_client(transport=replying({"reply": f"echo {SECRET}"}))
    client.post("/api/connection-tests", json=payload())
    client.post("/api/connection-tests", json=payload(response_path="$.missing"))
    client.post("/api/connection-tests", json=payload(url=""))
    assert all_logs().count(SECRET) == 0
