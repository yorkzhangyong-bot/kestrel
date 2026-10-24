"""The attacker model client: one HTTPS call per turn, nothing secret in it, failure is explicit (contracts/attacker.md).

Placeholder conversation text stands in for real content; these tests check the plumbing, not any attack text.
Async calls are driven through asyncio.run, matching tests/unit/test_judge_client.py.
"""
import asyncio
import json

import httpx
import pytest

from kestrel.attack.attacker import GOALS, MAX_MESSAGE_CHARS, AttackerClient, AttackerError

CONVERSATION = [("attacker", "<opening message>"), ("agent", "<agent reply one>")]


def client(handler, *, api_key="atk-key", model="deepseek/deepseek-v3.2", timeout=30.0) -> AttackerClient:
    return AttackerClient(model=model, api_key=api_key, base_url="https://atk.test/v1",
                          transport=httpx.MockTransport(handler), timeout=timeout)


def ask(the_client, conversation=CONVERSATION, progress="<a progress note>", family="system_prompt_leak"):
    return asyncio.run(the_client.next_message(conversation=conversation, progress=progress, family=family)).message


def returns(text="<next attacker message>", sink=None, tokens=150):
    def handler(request):
        if sink is not None:
            sink["body"] = json.loads(request.content)
            sink["auth"] = request.headers.get("authorization", "")
            sink["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}],
                                         "usage": {"total_tokens": tokens}})
    return handler


def test_it_returns_the_next_message():
    assert ask(client(returns("<the next move>"))) == "<the next move>"


def test_it_reports_the_tokens_the_call_used():
    reply = asyncio.run(client(returns(tokens=321)).next_message(
        conversation=CONVERSATION, progress=None, family="system_prompt_leak"))
    assert reply.tokens == 321


def test_there_is_a_goal_for_every_family():
    from kestrel.attack.attacker import FAMILIES_WITH_GOALS
    assert set(GOALS) == set(FAMILIES_WITH_GOALS)


def test_no_key_means_not_configured_and_no_request():
    calls = []
    c = client(lambda r: calls.append(r) or httpx.Response(200, json={}), api_key=None)
    assert c.configured is False
    with pytest.raises(AttackerError):
        ask(c)
    assert calls == []


def test_the_message_is_cut_to_the_cap():
    assert len(ask(client(returns("y" * 5000)))) <= MAX_MESSAGE_CHARS


def test_the_request_carries_the_conversation_and_progress_but_no_secret():
    sink = {}
    ask(client(returns(sink=sink)), conversation=[("attacker", "<m1>"), ("agent", "<r1>")], progress="<note>")
    body = json.dumps(sink["body"])
    assert "<m1>" in body and "<r1>" in body and "<note>" in body
    for secret in ("test-key-123", "https://my-agent.example.com/chat", "My production agent"):
        assert secret not in body
    assert sink["auth"] == "Bearer atk-key"  # key in the header, not the body


def test_the_model_name_is_sent():
    sink = {}
    ask(client(returns(sink=sink), model="deepseek/other"))
    assert sink["body"]["model"] == "deepseek/other"


def test_the_goal_reflects_the_family():
    sink = {}
    ask(client(returns(sink=sink)), family="tool_exfiltration")
    assert GOALS["tool_exfiltration"] in json.dumps(sink["body"])


@pytest.mark.parametrize("error", [httpx.ConnectError("x"), httpx.ReadTimeout("x")])
def test_a_transport_error_becomes_attacker_error(error):
    def handler(request):
        raise error
    with pytest.raises(AttackerError):
        ask(client(handler))


def test_a_non_200_becomes_attacker_error():
    with pytest.raises(AttackerError):
        ask(client(lambda r: httpx.Response(429, json={"error": "rate limited"})))


def test_an_empty_message_becomes_attacker_error():
    with pytest.raises(AttackerError):
        ask(client(returns("   ")))


def test_the_timeout_passed_in_is_honoured():
    sink = {}
    ask(client(returns(sink=sink), timeout=5.0))
    assert sink["timeout"]["read"] == 5.0
