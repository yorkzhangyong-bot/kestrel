"""Shared test helpers. A synthetic attack library and a stub judge, so integration tests need no real content."""
from __future__ import annotations

from kestrel.attacks.library import FAMILIES, build_library
from kestrel.judge.verdict import ParsedVerdict

OWASP = {key: meta["owasp_category"] for key, meta in FAMILIES.items()}


def fixture_library_data(version: str = "1.0.0") -> dict:
    """A valid library with five placeholder prompts per family (20 total). Ids are '<abbr>-00N'; no real text."""
    abbr = {"direct_injection": "dir", "system_prompt_leak": "spl",
            "tool_exfiltration": "tex", "indirect_injection": "iin"}
    prompts = []
    for family, prefix in abbr.items():
        for n in range(1, 6):
            prompts.append({"id": f"{prefix}-00{n}", "title": f"{family} placeholder {n}",
                            "text": f"<placeholder {family} prompt {n}>", "family": family,
                            "owasp_category": OWASP[family], "source": "Fixture", "source_url": "https://example.test",
                            "licence": "CC BY 4.0"})
    return {"version": version, "prompts": prompts}


def fixture_library(version: str = "1.0.0"):
    return build_library(fixture_library_data(version))


class StubJudge:
    """A judge that returns a fixed verdict (or raises), without touching the network."""

    def __init__(self, verdict: str = "failed", reason: str = "The agent held.", *, configured: bool = True,
                 model: str = "google/gemini-3.8-flash", error: Exception | None = None,
                 progress: str | None = "a step closer"):
        self._verdict, self._reason, self.configured, self.model = verdict, reason, configured, model
        self._error, self._progress = error, progress
        self.calls: list[dict] = []

    async def judge(self, *, attack: str, reply: str, conversation: str | None = None,
                    timeout: float | None = None) -> ParsedVerdict:
        self.calls.append({"attack": attack, "reply": reply, "conversation": conversation, "timeout": timeout})
        if self._error is not None:
            raise self._error
        return ParsedVerdict(self._verdict, self._reason, progress=self._progress)


class StubAttacker:
    """An attacker that emits a placeholder message each turn, without touching the network (feature 003)."""

    def __init__(self, *, configured: bool = True, model: str = "deepseek/deepseek-v3.2", tokens: int = 100,
                 error: Exception | None = None):
        self.configured, self.model, self._tokens, self._error = configured, model, tokens, error
        self.calls: list[dict] = []

    async def next_message(self, *, conversation, family, progress=None, timeout=None):
        from kestrel.attack.attacker import AttackerReply
        self.calls.append({"conversation": conversation, "family": family, "progress": progress})
        if self._error is not None:
            raise self._error
        return AttackerReply(message=f"<attacker turn {len(conversation) // 2 + 1}>", tokens=self._tokens)
