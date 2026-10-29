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

FAMILY = "system_prompt_leak"
OWASP = "LLM07: System Prompt Leakage"
ATTACK = "<winning attacker message placeholder>"
EVIDENCE = "KESTREL-CANARY-9Z"


def client(handler, *, api_key="judge-key") -> JudgeClient:
    return JudgeClient(model="google/gemini-3.8-flash", api_key=api_key, base_url="https://judge.test/v1",
                       transport=httpx.MockTransport(handler))


def recommend(the_client):
    return asyncio.run(the_client.recommend(family=FAMILY, owasp_category=OWASP, attack=ATTACK, evidence=EVIDENCE))


def test_recommend_returns_text_and_tokens():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content":
                             json.dumps({"recommendation": "Refuse to reveal the system prompt."})}}],
                             "usage": {"total_tokens": 123}})
    text, tokens = recommend(client(handler))
    assert "Refuse" in text and tokens == 123


def test_recommend_posts_only_non_secret_fields():
    sink = {}

    def handler(request):
        sink["body"] = json.loads(request.content)
        sink["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"choices": [{"message": {"content":
                             json.dumps({"recommendation": "Harden it."})}}]})
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
        return httpx.Response(502, text="upstream error")
    with pytest.raises(JudgeError):
        recommend(client(handler))
