"""The attacker accepts an optional hints block; without it the request is unchanged from feature 003 (FR-019, SC-007)."""
import asyncio
import json

import httpx

from kestrel.attack.attacker import GOALS, SYSTEM_PROMPT, AttackerClient

CONVERSATION = [("attacker", "<m1>"), ("agent", "<r1>")]


def client(sink):
    def handler(request):
        sink["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "<next>"}}],
                                         "usage": {"total_tokens": 10}})
    return AttackerClient(model="m", api_key="k", base_url="https://atk.test/v1",
                          transport=httpx.MockTransport(handler))


def system_text(body) -> str:
    return "\n".join(m["content"] for m in body["messages"] if m["role"] == "system")


def test_no_hints_keeps_the_feature_003_system_prompt():
    sink = {}
    asyncio.run(client(sink).next_message(conversation=CONVERSATION, family="system_prompt_leak", hints=None))
    assert system_text(sink["body"]).strip() == SYSTEM_PROMPT.format(goal=GOALS["system_prompt_leak"]).strip()


def test_hints_are_added_to_the_system_prompt():
    sink = {}
    asyncio.run(client(sink).next_message(conversation=CONVERSATION, family="system_prompt_leak",
                                          hints="[background] <<MEMORY AND PATTERNS>>"))
    text = system_text(sink["body"])
    assert "<<MEMORY AND PATTERNS>>" in text
    assert GOALS["system_prompt_leak"] in text   # the goal is still there too
