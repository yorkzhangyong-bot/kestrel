"""The judge client: one HTTPS call, nothing secret in it, every failure becomes "unreachable" (contracts/judge.md).

Benign placeholder text stands in for a real attack here; these tests check the plumbing, not the content.
Async calls are driven through asyncio.run, matching tests/unit/test_tester.py.
"""
import asyncio
import json

import httpx
import pytest

from kestrel.judge.client import JudgeClient, JudgeError

FEATURE = "002"

ATTACK = "<attack prompt placeholder>"
REPLY = "The agent answered its ordinary task."


def client(handler, *, api_key="judge-key", model="google/gemini-3.8-flash", timeout=30.0) -> JudgeClient:
    return JudgeClient(model=model, api_key=api_key, base_url="https://judge.test/v1",
                       transport=httpx.MockTransport(handler), timeout=timeout)


def judge(the_client, attack=ATTACK, reply=REPLY):
    return asyncio.run(the_client.judge(attack=attack, reply=reply))


def ok(body: dict):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body)}}]})
    return handler


def content_handler(sink: dict, verdict="failed"):
    def handler(request):
        sink["body"] = json.loads(request.content)
        sink["auth"] = request.headers.get("authorization", "")
        sink["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json={"choices": [{"message": {"content":
                             json.dumps({"verdict": verdict, "reason": "x"})}}]})
    return handler


def test_a_clean_answer_comes_back_as_a_verdict():
    result = judge(client(ok({"verdict": "failed", "reason": "The agent refused."})))
    assert result.verdict == "failed" and result.reason == "The agent refused."


def test_no_key_means_not_configured_and_no_request_is_made():
    """Canary evidence still works without a judge, so an absent key must not send anything (FR-021)."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})

    the_client = client(handler, api_key=None)
    assert the_client.configured is False
    with pytest.raises(JudgeError):
        judge(the_client)
    assert calls == []  # nothing left the machine


def test_the_reply_is_cut_to_2000_characters_before_sending():
    sink = {}
    judge(client(content_handler(sink)), reply="y" * 5000)
    whole = json.dumps(sink["body"])
    assert "y" * 2001 not in whole and "y" * 2000 in whole


def test_the_answer_is_capped_at_200_tokens():
    sink = {}
    judge(client(content_handler(sink)))
    assert sink["body"]["max_tokens"] == 200


def test_the_request_carries_no_secret_or_identifying_detail():
    """The judge must never receive an auth header value, the target URL, or the target name (FR-020)."""
    sink = {}
    judge(client(content_handler(sink)))
    text = json.dumps(sink["body"])
    for secret in ("test-key-123", "https://my-agent.example.com/chat", "My production agent"):
        assert secret not in text
    assert sink["auth"] == "Bearer judge-key"  # the judge's own key, in the header, not the body


def test_the_model_name_is_sent():
    sink = {}
    judge(client(content_handler(sink), model="anthropic/claude-haiku-4.5"))
    assert sink["body"]["model"] == "anthropic/claude-haiku-4.5"


@pytest.mark.parametrize("error", [httpx.ConnectError("no route"), httpx.ReadTimeout("slow")])
def test_a_transport_error_becomes_judge_unreachable(error):
    def handler(request):
        raise error
    with pytest.raises(JudgeError):
        judge(client(handler))


def test_a_non_200_status_becomes_judge_unreachable():
    def handler(request):
        return httpx.Response(429, json={"error": "rate limited"})
    with pytest.raises(JudgeError):
        judge(client(handler))


def test_an_unreadable_answer_becomes_an_error():
    with pytest.raises(JudgeError):
        judge(client(ok({"verdict": "not-a-verdict", "reason": "x"})))


def test_the_timeout_passed_in_is_honoured():
    """runs.py shortens this to what is left of the 90-second deadline (FR-013)."""
    sink = {}
    judge(client(content_handler(sink), timeout=5.0))
    assert sink["timeout"]["read"] == 5.0
