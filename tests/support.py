"""Shared test helpers. A synthetic attack library and a stub judge, so integration tests need no real content."""
from __future__ import annotations

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
