"""run_test against httpx.MockTransport targets: research R2 rows 2 and 4 to 13 (rows 1 and 3 come from the API)."""
import asyncio
import json
import logging
import socket

import httpx
import pytest

from kestrel.connection.tester import MESSAGES, ResolvedSettings, run_test
from kestrel.secrets import MASK

SECRET = "s3cret-header-value"


def make(url="http://agent.test/chat", method="POST", headers=(("X-API-Key", SECRET),),
         template='{"message": "{{prompt}}"}', path="$.reply") -> ResolvedSettings:
    return ResolvedSettings(url=url, method=method, headers=headers, body_template=template, response_path=path)


def run(settings, handler=None, **kwargs):
    kwargs.setdefault("mode", "local")
    if handler is not None:
        kwargs.setdefault("transport", httpx.MockTransport(handler))
    return asyncio.run(run_test(settings, **kwargs))


def reply(body, status=200, **kwargs):
    return lambda request: httpx.Response(status, json=body, **kwargs)


def assert_step(outcome, step, *, ok=False):
    assert outcome.step == step
    assert outcome.ok is ok
    assert outcome.message == MESSAGES[step]


def test_success_returns_the_reply_text():
    outcome = run(make(), reply({"reply": "Hi there"}))
    assert_step(outcome, "success", ok=True)
    assert outcome.reply_text == "Hi there"
    assert outcome.status_code == 200
    assert outcome.reply_truncated is False
    assert outcome.duration_ms >= 0


def test_exactly_one_request_with_hello_and_the_users_headers():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"reply": "ok"})

    run(make(), handler)
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert json.loads(request.content) == {"message": "Hello"}
    assert request.headers["x-api-key"] == SECRET
    assert request.headers["user-agent"] == "Kestrel/0.1 (connection test)"
    assert request.headers["content-type"] == "application/json"


def test_get_puts_hello_in_the_query_and_sends_no_body():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"reply": "ok"})

    run(make(url="http://agent.test/chat?q={{prompt}}", method="GET"), handler)
    assert seen[0].method == "GET"
    assert seen[0].url.params["q"] == "Hello"
    assert seen[0].content == b""


def test_empty_reply_is_a_success():
    outcome = run(make(), reply({"reply": ""}))
    assert_step(outcome, "success", ok=True)
    assert outcome.reply_text == ""


@pytest.mark.parametrize("status", [401, 403])
def test_401_and_403_are_authentication_rejected(status):
    outcome = run(make(), reply({"error": "no"}, status=status))
    assert_step(outcome, "auth_rejected")
    assert outcome.detail == f"Status {status}"
    assert outcome.status_code == status


def test_a_redirect_is_not_followed_and_names_the_location():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://elsewhere.test/chat"})

    outcome = run(make(), handler)
    assert_step(outcome, "endpoint_error")
    assert "302" in outcome.detail and "https://elsewhere.test/chat" in outcome.detail
    assert len(seen) == 1


def test_a_server_error_is_an_endpoint_error():
    outcome = run(make(), reply({"error": "boom"}, status=500))
    assert_step(outcome, "endpoint_error")
    assert outcome.detail == "Status 500"


def test_a_body_over_1_mb_by_content_length_is_an_endpoint_error():
    outcome = run(make(), lambda request: httpx.Response(200, content=b"{" + b" " * 1_048_577 + b"}"))
    assert_step(outcome, "endpoint_error")
    assert outcome.detail == "Response larger than 1 MB"


def test_a_streamed_body_over_1_mb_without_content_length_is_an_endpoint_error():
    async def chunks():
        for _ in range(20):
            yield b" " * 65_536

    def handler(request):
        response = httpx.Response(200, content=chunks())
        assert "content-length" not in response.headers
        return response

    outcome = run(make(), handler)
    assert_step(outcome, "endpoint_error")
    assert outcome.detail == "Response larger than 1 MB"


def test_a_body_that_is_not_json_is_non_json():
    outcome = run(make(), lambda request: httpx.Response(200, content=b"<html>hi</html>"))
    assert_step(outcome, "non_json")


def test_a_missing_path_is_path_not_found():
    assert_step(run(make(), reply({"answer": "x"})), "path_not_found")


@pytest.mark.parametrize("value, found", [([1, 2], "list"), ({"a": 1}, "object"), (3, "number"),
                                          (None, "null"), (True, "boolean")])
def test_a_path_matching_something_other_than_text_is_not_text(value, found):
    outcome = run(make(), reply({"reply": value}))
    assert_step(outcome, "not_text")
    assert outcome.detail == f"Found: {found}"


def test_a_closed_port_is_unreachable():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    outcome = run(make(url=f"http://127.0.0.1:{port}/chat"))
    assert_step(outcome, "unreachable")


def test_a_certificate_failure_is_unreachable_and_named():
    def handler(request):
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed", request=request)

    outcome = run(make(url="https://agent.test/chat"), handler)
    assert_step(outcome, "unreachable")
    assert "certificate verify failed" in outcome.detail


def test_no_answer_before_the_deadline_is_timed_out():
    async def handler(request):
        await asyncio.sleep(2)
        return httpx.Response(200, json={"reply": "late"})

    assert_step(run(make(), handler, deadline_s=0.5), "timed_out")


def test_hosted_mode_refuses_a_private_address_before_sending():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"reply": "ok"})

    outcome = run(make(url="http://10.0.0.5/chat"), handler, mode="hosted")
    assert_step(outcome, "address_not_allowed")
    assert seen == []


def test_a_long_reply_is_cut_to_2000_characters():
    outcome = run(make(), reply({"reply": "a" * 2500}))
    assert len(outcome.reply_text) == 2000
    assert outcome.reply_truncated is True


def test_header_values_echoed_in_a_reply_or_detail_are_masked():
    outcome = run(make(), reply({"reply": f"your key is {SECRET}"}))
    assert outcome.reply_text == f"your key is {MASK}"
    redirect = run(make(), lambda request: httpx.Response(302, headers={"Location": f"https://x.test/?k={SECRET}"}))
    assert SECRET not in redirect.detail and MASK in redirect.detail


def test_one_log_line_without_query_string_header_value_or_reply(caplog):
    caplog.set_level(logging.INFO, logger="kestrel.connection")
    run(make(url="http://h:8001/chat?q={{prompt}}&lang=en", method="GET"), reply({"reply": "the secret reply"}),
        display_name="Agent")
    lines = [r.getMessage() for r in caplog.records if r.name == "kestrel.connection"]
    assert len(lines) == 1
    line = lines[0]
    assert "http://h:8001/chat" in line
    assert "?" not in line and "q=" not in line and "Hello" not in line
    for expected in ("Agent", "GET", "success", "200", "duration_ms"):
        assert expected in line
    assert SECRET not in caplog.text and "the secret reply" not in caplog.text
