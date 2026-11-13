"""The attacker's hints ride as fenced *data* in a user message, never in the fixed system prompt (FR-019, SC-007).

Without hints the request keeps feature-003 behaviour (the fixed system prompt plus the shared data rule).
"""
import asyncio
import json

import httpx

from kestrel import prompt_registry
from kestrel.attack.attacker import AttackerClient
from kestrel.prompting import DATA_RULE

FEATURE = "004"
# Also traces feature 008 (hardening): 008/FR-007 (data rule in system), 008/FR-008 (hints outside the system role).

CONVERSATION = [("attacker", "<m1>"), ("agent", "<r1>")]
FAMILY_PROMPT = prompt_registry.load_prompt(prompt_registry.attacker_id("system_prompt_leak"))[0]


async def _noop(_delay):
    return None


def client(sink):
    def handler(request):
        sink["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "<next>"}}],
                                         "usage": {"total_tokens": 10}})
    return AttackerClient(model="m", api_key="k", base_url="https://atk.test/v1",
                          transport=httpx.MockTransport(handler), sleep=_noop)


def role_text(body, role) -> str:
    return "\n".join(m["content"] for m in body["messages"] if m["role"] == role)


def test_no_hints_keeps_the_fixed_system_prompt_plus_the_data_rule():
    sink = {}
    asyncio.run(client(sink).next_message(conversation=CONVERSATION, family="system_prompt_leak", hints=None))
    system = role_text(sink["body"], "system")
    assert system.strip() == f"{FAMILY_PROMPT}\n\n{DATA_RULE}".strip()
    assert "background" not in role_text(sink["body"], "user").lower()   # no extra hints message


def test_hints_go_in_a_separate_fenced_user_message_not_the_system_prompt():
    sink = {}
    asyncio.run(client(sink).next_message(conversation=CONVERSATION, family="system_prompt_leak",
                                          hints="MEMORY-AND-PATTERNS-MARKER"))
    system = role_text(sink["body"], "system")
    user = role_text(sink["body"], "user")
    assert "MEMORY-AND-PATTERNS-MARKER" not in system      # hints never ride in the system role
    assert "MEMORY-AND-PATTERNS-MARKER" in user            # they are background data, in a user message
    assert '<untrusted kind="background">' in user         # fenced as data (item 3)
    assert FAMILY_PROMPT in system and DATA_RULE in system   # the family prompt and the rule stay in system
