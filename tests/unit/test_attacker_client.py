"""The attacker model client: one HTTPS call per turn, nothing secret in it, failure is explicit (contracts/attacker.md).

Placeholder conversation text stands in for real content; these tests check the plumbing, not any attack text.
Async calls are driven through asyncio.run, matching tests/unit/test_judge_client.py.
"""
import asyncio
import json

import httpx
import pytest

from kestrel import prompt_registry
from kestrel.attack.attacker import MAX_MESSAGE_CHARS, AttackerClient, AttackerError
from kestrel.retry import RETRY_ATTEMPTS

# Traces feature 008 (hardening): 008/FR-009 (retry transient statuses), 008/FR-010 (deadline, tokens).

CONVERSATION = [("attacker", "<opening message>"), ("agent", "<agent reply one>")]


async def _noop(_delay):
    return None


def client(handler, *, api_key="atk-key", model="deepseek/deepseek-v3.2", timeout=30.0) -> AttackerClient:
    return AttackerClient(model=model, api_key=api_key, base_url="https://atk.test/v1",
                          transport=httpx.MockTransport(handler), timeout=timeout, sleep=_noop)


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


def test_there_is_an_attacker_prompt_for_every_family():
    from kestrel.store import FAMILIES
    assert set(prompt_registry.families()) == set(FAMILIES)   # feature 009: one prompt file per family


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


def test_the_system_prompt_reflects_the_family():
    sink = {}
    ask(client(returns(sink=sink)), family="tool_exfiltration")
    system = sink["body"]["messages"][0]["content"]
    assert prompt_registry.load_prompt("attacker:tool_exfiltration")[0] in system
    assert prompt_registry.load_prompt("attacker:system_prompt_leak")[0] not in system


def test_a_family_without_a_registered_prompt_is_an_attacker_error():
    calls = []
    with pytest.raises(AttackerError):
        ask(client(lambda r: calls.append(r) or httpx.Response(200, json={})), family="no_such_family")
    assert calls == []   # refused before any model call (feature 009)


@pytest.mark.parametrize("error", [httpx.ConnectError("x"), httpx.ReadTimeout("x")])
def test_a_transport_error_becomes_attacker_error(error):
    def handler(request):
        raise error
    with pytest.raises(AttackerError):
        ask(client(handler))


def test_a_persistent_transient_status_is_retried_then_becomes_attacker_error():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, json={"error": "rate limited"})
    with pytest.raises(AttackerError):
        ask(client(handler))
    assert len(calls) == RETRY_ATTEMPTS   # the transient status was retried before giving up (item 4)


def test_a_non_retryable_status_is_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"error": "bad request"})
    with pytest.raises(AttackerError):
        ask(client(handler))
    assert len(calls) == 1


def test_a_transient_status_then_a_message_recovers():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503, json={"usage": {"total_tokens": 4}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "<recovered>"}}],
                                         "usage": {"total_tokens": 20}})
    reply = asyncio.run(client(handler).next_message(conversation=CONVERSATION, family="system_prompt_leak"))
    assert reply.message == "<recovered>" and reply.tokens == 24 and len(calls) == 2


def test_an_empty_message_becomes_attacker_error():
    with pytest.raises(AttackerError):
        ask(client(returns("   ")))


def _empty(reasoning_tokens=400, total=400):
    """A reasoning model's response that spent the whole budget on reasoning: empty content, finish_reason length."""
    return {"choices": [{"message": {"content": "", "reasoning": "r" * 40}, "finish_reason": "length"}],
            "usage": {"total_tokens": total, "completion_tokens": total,
                      "completion_tokens_details": {"reasoning_tokens": reasoning_tokens}}}


def test_it_retries_once_on_an_empty_message_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=_empty(total=400))                       # first: empty (reasoning only)
        return httpx.Response(200, json={"choices": [{"message": {"content": "<recovered move>"}}],
                                         "usage": {"total_tokens": 120}})             # retry: real content
    reply = asyncio.run(client(handler).next_message(conversation=CONVERSATION, family="system_prompt_leak"))
    assert reply.message == "<recovered move>"
    assert len(calls) == 2                        # tried once, retried once
    assert reply.tokens == 520                    # both attempts count toward the run budget (400 + 120)


def test_it_stops_after_a_second_empty_message():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_empty())
    with pytest.raises(AttackerError, match="empty message"):
        asyncio.run(client(handler).next_message(conversation=CONVERSATION, family="system_prompt_leak"))
    assert len(calls) == 2                        # exactly one retry, then stop


def test_an_empty_message_is_logged_with_diagnostics(json_log):
    # 010/FR-003: the same diagnostics, now as the fields of a `model.empty_content` line instead of message text.
    with pytest.raises(AttackerError):
        asyncio.run(client(lambda r: httpx.Response(200, json=_empty(reasoning_tokens=400, total=400)))
                    .next_message(conversation=CONVERSATION, family="system_prompt_leak"))
    first = json_log.of("model.empty_content")[0]
    assert first["finish_reason"] == "length" and first["reasoning_tokens"] == 400
    assert (first["level"], first["attempt"], first["completion_tokens"], first["total_tokens"],
            first["reasoning_chars"]) == ("WARNING", 1, 400, 400, 40)


def test_the_timeout_passed_in_is_honoured():
    sink = {}
    ask(client(returns(sink=sink), timeout=5.0))
    assert sink["timeout"]["read"] == 5.0


# ---- feature 010: one model.request line per logical call, and the prompt reference the client sends ----


def _ask_logged(handler, **kwargs):
    return asyncio.run(client(handler, **kwargs).next_message(conversation=CONVERSATION, family="system_prompt_leak"))


def test_a_call_emits_one_model_request_line(json_log):  # 010/FR-003, 010/FR-008
    reply = _ask_logged(returns("<next move>", tokens=150))
    line = json_log.of("model.request")[0]
    assert len(json_log.of("model.request")) == 1
    assert (line["kind"], line["model"], line["prompt"]) == ("attacker", "deepseek/deepseek-v3.2",
                                                             "attacker:system_prompt_leak@1")
    assert line["latency_ms"] >= 0 and line["ok"] is True and line["status"] == 200 and line["attempts"] == 1
    assert (line["prompt_tokens"], line["completion_tokens"], line["total_tokens"]) == (None, None, 150)
    assert line["cost_usd"] is None
    assert line["cost_note"] == "unavailable (no configured price for deepseek/deepseek-v3.2)"
    assert line["message_chars"] == len(reply.message) and "error" not in line and line["level"] == "INFO"


def test_a_priced_model_gets_its_cost(json_log):  # 010/FR-008, 010/SC-006
    from kestrel import events
    events.configure(prices={"deepseek/deepseek-v3.2": 0.002})
    _ask_logged(returns(tokens=150))
    line = json_log.of("model.request")[0]
    assert abs(line["cost_usd"] - 150 / 1000 * 0.002) < 1e-9 and "cost_note" not in line


def test_an_empty_then_good_answer_is_one_line_counting_both_attempts(json_log):  # 010/FR-003
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=_empty(total=400))
        return httpx.Response(200, json={"choices": [{"message": {"content": "<move>"}}],
                                         "usage": {"total_tokens": 120}})
    _ask_logged(handler)
    lines = json_log.of("model.request")
    assert len(lines) == 1 and lines[0]["attempts"] == 2 and lines[0]["total_tokens"] == 520


def test_a_failed_call_logs_the_status_and_the_error_class_only(json_log):  # 010/FR-003, 010/FR-009
    with pytest.raises(AttackerError):
        _ask_logged(lambda r: httpx.Response(400, json={"error": {"message": "provider says no-such-model"}}))
    line = json_log.of("model.request")[0]
    assert line["ok"] is False and line["status"] == 400 and line["error"] == "AttackerError"
    assert line["level"] == "ERROR" and "message_chars" not in line and line["total_tokens"] is None
    assert "no-such-model" not in json_log.text()


def test_an_unreachable_model_logs_the_transport_error_class(json_log):  # 010/FR-003
    def handler(request):
        raise httpx.ConnectError("connection refused to a private address", request=request)
    with pytest.raises(AttackerError):
        _ask_logged(handler)
    line = json_log.of("model.request")[0]
    assert line["error"] == "ConnectError" and line["status"] is None and line["attempts"] == 1
    assert "private address" not in json_log.text()


def test_the_client_exposes_the_reference_it_sends(json_log):  # 010/FR-007
    active = AttackerClient(model="m", api_key="k", base_url="https://atk.test/v1")
    assert active.prompt_ref("system_prompt_leak") == "attacker:system_prompt_leak@1"
    assert active.prompt_ref("no_such_family") is None
    pinned = AttackerClient(model="m", api_key="k", base_url="https://atk.test/v1",
                            system_overrides={"system_prompt_leak": ("PINNED TEXT", "attacker:system_prompt_leak@7")})
    assert pinned.prompt_ref("system_prompt_leak") == "attacker:system_prompt_leak@7"
    assert "PINNED TEXT" in pinned._payload([], None, "system_prompt_leak")["messages"][0]["content"]
    assert pinned.prompt_ref("direct_injection") == "attacker:direct_injection@1"   # other families: active
    plain = AttackerClient(model="m", api_key="k", base_url="https://atk.test/v1",
                           system_overrides={"system_prompt_leak": "A PLAIN PINNED TEXT"})
    assert plain.prompt_ref("system_prompt_leak") is None   # the feature-009 form: the reference is not known


def test_a_pinned_reference_is_the_one_on_the_line(json_log):  # 010/FR-007
    pinned = AttackerClient(model="m", api_key="k", base_url="https://atk.test/v1", sleep=_noop,
                            transport=httpx.MockTransport(returns()),
                            system_overrides={"system_prompt_leak": ("PINNED", "attacker:system_prompt_leak@7")})
    asyncio.run(pinned.next_message(conversation=CONVERSATION, family="system_prompt_leak"))
    assert json_log.of("model.request")[0]["prompt"] == "attacker:system_prompt_leak@7"
