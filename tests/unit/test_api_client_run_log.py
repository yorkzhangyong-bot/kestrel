"""The screen's client for a run's log (010/FR-011, 010/FR-012): `api_client.get_run_log` asks the configured API for
`GET /api/runs/{id}/log` (with the hosted token when one is set) and returns its body, or raises ApiError with the
API's status and body — so a UI/API mismatch fails here rather than hiding behind the screen tests' stub."""
import httpx
import pytest

import api_client

FEATURE = "010"

# The real client function, taken at collection — before tests/conftest.py's autouse stub replaces it for each test.
REAL_GET_RUN_LOG = api_client.get_run_log

BODY = {"run_id": 7, "lines": [{"event": "run.start", "run_id": 7}], "kept": 1, "dropped": 0, "truncated": False}


@pytest.fixture
def api(monkeypatch):
    """Put the real `get_run_log` back over the autouse stub (monkeypatch applies last) and route api_client's HTTP
    calls through a MockTransport; record every request."""
    monkeypatch.setattr(api_client, "get_run_log", REAL_GET_RUN_LOG)
    seen: list[httpx.Request] = []
    replies = {"status": 200, "body": BODY}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(replies["status"], json=replies["body"])

    def request(method, url, **kwargs):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            return client.request(method, url, **kwargs)

    monkeypatch.setattr(httpx, "request", request)
    monkeypatch.setenv("KESTREL_API_URL", "http://api.kestrel.test/")
    monkeypatch.setenv("KESTREL_API_TOKEN", "t0ken-for-tests")
    return seen, replies


def test_get_run_log_gets_the_runs_log_endpoint_and_returns_its_body(api):  # FR-011, FR-012
    seen, _replies = api
    assert api_client.get_run_log(7) == BODY
    (request,) = seen
    assert request.method == "GET" and str(request.url) == "http://api.kestrel.test/api/runs/7/log"
    assert request.headers["X-Kestrel-Token"] == "t0ken-for-tests"


def test_an_error_answer_becomes_an_api_error_with_the_apis_body(api):  # FR-011, FR-012
    _seen, replies = api
    replies["status"], replies["body"] = 404, {"error": {"code": "not_found", "field": None,
                                                         "message": "No run with id 7."}}
    with pytest.raises(api_client.ApiError) as raised:
        api_client.get_run_log(7)
    assert raised.value.status == 404 and raised.value.body == replies["body"]
