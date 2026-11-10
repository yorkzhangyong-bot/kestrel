"""JudgeClient.recommend: one call, non-secret inputs only, text + tokens out, JudgeError when unconfigured (FR-018).

Benign placeholder text stands in for a real attack here; these tests check the plumbing, not the content.
Async calls are driven through asyncio.run, matching tests/unit/test_judge_client.py.
"""
import asyncio
import json

import httpx
import pytest

from kestrel.judge.client import JudgeClient, JudgeError

FEATURE = "005"
# Also traces feature 008 (hardening): 008/FR-004 (recommendation validate + retry), 008/FR-006 (fenced inputs).

FAMILY = "system_prompt_leak"
OWASP = "LLM07: System Prompt Leakage"
ATTACK = "winning attacker message placeholder"   # no angle brackets, so the fenced copy is easy to assert
EVIDENCE = "KESTREL-CANARY-9Z"


async def _noop(_delay):
    return None


def client(handler, *, api_key="judge-key") -> JudgeClient:
    return JudgeClient(model="google/gemini-3.8-flash", api_key=api_key, base_url="https://judge.test/v1",
                       transport=httpx.MockTransport(handler), sleep=_noop)


def recommend(the_client):
    return asyncio.run(the_client.recommend(family=FAMILY, owasp_category=OWASP, attack=ATTACK, evidence=EVIDENCE))


def _recommendation(text="Refuse to reveal the system prompt.") -> str:
    return json.dumps({"recommendation": text})


def test_recommend_returns_text_and_tokens():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": _recommendation()}}],
                             "usage": {"total_tokens": 123}})
    text, tokens = recommend(client(handler))
    assert "Refuse" in text and tokens == 123


def test_recommend_posts_only_non_secret_fields():
    sink = {}

    def handler(request):
        sink["body"] = json.loads(request.content)
        sink["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"choices": [{"message": {"content": _recommendation("Harden it.")}}]})
    recommend(client(handler, api_key="super-secret-key"))
    blob = json.dumps(sink["body"])
    assert FAMILY in blob and "LLM07" in blob and ATTACK in blob and EVIDENCE in blob   # the four inputs went out
    assert "super-secret-key" in sink["auth"] and "super-secret-key" not in blob        # key rides the header only


def test_recommend_raises_when_not_configured():
    def handler(request):
        raise AssertionError("recommend must not touch the network when unconfigured")
    with pytest.raises(JudgeError):
        recommend(client(handler, api_key=None))


def test_recommend_raises_on_a_bad_status():
    def handler(request):
        return httpx.Response(500, text="upstream error")
    with pytest.raises(JudgeError):
        recommend(client(handler))


def test_a_bad_recommendation_is_retried_once_then_accepted():
    """A reply that fails validation is retried once with feedback, same as the verdict path (item 1)."""
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "sorry, no JSON here"}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": _recommendation("Add an allowlist.")}}]})
    text, _tokens = recommend(client(handler))
    assert text == "Add an allowlist." and len(calls) == 2
