"""Shared test helpers. A synthetic attack library and a stub judge, so integration tests need no real content."""
from __future__ import annotations

import json

import httpx
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

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
                 progress: str | None = "a step closer", recommendation: str = "Harden the system prompt."):
        self._verdict, self._reason, self.configured, self.model = verdict, reason, configured, model
        self._error, self._progress, self._recommendation = error, progress, recommendation
        self.calls: list[dict] = []

    async def judge(self, *, attack: str, reply: str, conversation: str | None = None,
                    timeout: float | None = None) -> ParsedVerdict:
        self.calls.append({"attack": attack, "reply": reply, "conversation": conversation, "timeout": timeout})
        if self._error is not None:
            raise self._error
        return ParsedVerdict(self._verdict, self._reason, progress=self._progress)

    async def recommend(self, *, family: str, owasp_category: str, attack: str, evidence: str,
                        timeout: float | None = None) -> tuple[str, int]:
        self.calls.append({"recommend": True, "family": family, "owasp_category": owasp_category,
                           "attack": attack, "evidence": evidence, "timeout": timeout})
        if self._error is not None:
            raise self._error
        return self._recommendation, 42


class StubAttacker:
    """An attacker that emits a placeholder message each turn, without touching the network (feature 003)."""

    def __init__(self, *, configured: bool = True, model: str = "deepseek/deepseek-v3.2", tokens: int = 100,
                 error: Exception | None = None):
        self.configured, self.model, self._tokens, self._error = configured, model, tokens, error
        self.calls: list[dict] = []

    async def next_message(self, *, conversation, family, progress=None, hints=None, timeout=None):
        from kestrel.attack.attacker import AttackerReply
        self.calls.append({"conversation": conversation, "family": family, "progress": progress, "hints": hints})
        if self._error is not None:
            raise self._error
        return AttackerReply(message=f"<attacker turn {len(conversation) // 2 + 1}>", tokens=self._tokens)

    @property
    def last_hints(self) -> str | None:
        """The hints block passed to the most recent next_message call (for warm/cold tests)."""
        return self.calls[-1]["hints"] if self.calls else None


class StubEmbeddingFunction(EmbeddingFunction):
    """A deterministic, offline embedding function for ExperienceStore tests (research R2).

    Keeps `uv run pytest` free of model downloads and network. Similarity is crude but stable: it is
    enough to exercise retrieval filtering and selection, not embedding quality (that is the e2e's job).
    Inherits the chromadb EmbeddingFunction surface so the collection persists and reopens cleanly.
    """

    def __init__(self, dim: int = 32) -> None:
        self._dim = dim

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002 - chromadb's parameter name is `input`
        vectors = []
        for document in input:
            vector = [0.0] * self._dim
            for index, char in enumerate(document):
                vector[index % self._dim] += (ord(char) % 17) / 17.0
            vectors.append(vector)
        return vectors

    @staticmethod
    def name() -> str:
        return "kestrel_stub"

    def get_config(self) -> dict:
        return {"dim": self._dim}

    @classmethod
    def build_from_config(cls, config: dict) -> "StubEmbeddingFunction":
        return cls(dim=config.get("dim", 32))


# ---- feature 010: known strings, and one offline transport for the target and the real model clients ----

# Known strings the redaction tests count on every surface (010/SC-002). Placeholders only, never attack text.
SECRET = "KESTREL-TEST-AUTH-VALUE-9f3a71"              # the target's auth header value
TARGET_URL = "http://target.kestrel.test/agent/chat"    # the target's URL
TARGET_NAME = "Redaction Probe Agent 7"                 # the target's display name
ATTACK_TEXT = "<attack message placeholder 4471>"       # the message sent to the target
REPLY_TEXT = "<target reply placeholder 8823>"          # the target's reply
JUDGE_REASON = "The reply quoted <target reply placeholder 8823> back."   # judge free text quoting the reply
JUDGE_PROGRESS = "progress note placeholder 5531"
MODEL_KEY = "KESTREL-TEST-MODEL-KEY-c0ffee"             # the attacker/judge API key
MODEL_BASE_URL = "http://models.kestrel.test/v1"        # the model endpoint the real clients call


async def no_sleep(_delay):
    return None


class ModelTransport:
    """One httpx.MockTransport for a whole offline run (010/T003): it answers the model endpoint — attacker, judge and
    recommender requests, told apart by the request's response_format — with canned OpenAI-style bodies carrying a
    `usage` object, and every other host as the stub target ({"reply": ...}). Every request is recorded with its
    headers, so a test can check what reached the target. Pass `.transport` both as the app's transport and as the
    real clients' transport."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.target_reply = REPLY_TEXT
        self.target_status = 200
        self.attacker_message = ATTACK_TEXT
        self.attacker_statuses: list[int] = []      # consumed one per attacker POST; 200 once empty
        self.verdict = "failed"
        self.judge_reason = JUDGE_REASON
        self.judge_progress = JUDGE_PROGRESS
        self.judge_statuses: list[int] = []
        self.recommendation = "Keep the system prompt out of replies."
        self.usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        self.transport = httpx.MockTransport(self.handle)

    # -- what a test reads back --

    def target_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host != httpx.URL(MODEL_BASE_URL).host]

    def model_requests(self, kind: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == httpx.URL(MODEL_BASE_URL).host and _kind(r) == kind]

    # -- the handler --

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host != httpx.URL(MODEL_BASE_URL).host:
            return httpx.Response(self.target_status, json={"reply": self.target_reply})
        kind = _kind(request)
        if kind == "attacker":
            status = self.attacker_statuses.pop(0) if self.attacker_statuses else 200
            content = self.attacker_message
        elif kind == "judge":
            status = self.judge_statuses.pop(0) if self.judge_statuses else 200
            content = json.dumps({"verdict": self.verdict, "reason": self.judge_reason,
                                  "progress": self.judge_progress})
        else:
            status, content = 200, json.dumps({"recommendation": self.recommendation})
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "placeholder provider error"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                         "usage": dict(self.usage)})


def _kind(request: httpx.Request) -> str:
    """attacker (no response_format), judge (schema "verdict") or recommender (schema "recommendation")."""
    body = json.loads(request.content or b"{}")
    schema = ((body.get("response_format") or {}).get("json_schema") or {}).get("name")
    return {"verdict": "judge", "recommendation": "recommender"}.get(schema, "attacker")


def real_judge(model_transport: ModelTransport, *, model: str = "google/gemini-3.8-flash", system_prompt=None):
    """The real JudgeClient over the offline transport (010, research D10)."""
    from kestrel.judge.client import JudgeClient
    return JudgeClient(model=model, api_key=MODEL_KEY, base_url=MODEL_BASE_URL, transport=model_transport.transport,
                       sleep=no_sleep, system_prompt=system_prompt)


def real_attacker(model_transport: ModelTransport, *, model: str = "deepseek/deepseek-v4.1-flash",
                  system_overrides=None):
    """The real AttackerClient over the offline transport (010, research D10)."""
    from kestrel.attack.attacker import AttackerClient
    return AttackerClient(model=model, api_key=MODEL_KEY, base_url=MODEL_BASE_URL,
                          transport=model_transport.transport, sleep=no_sleep, system_overrides=system_overrides)
