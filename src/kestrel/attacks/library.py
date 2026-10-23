"""The built-in attack library: loaded once, validated, indexed by family (contracts/attack-library.md).

Prompts are curated from published, citable sources and carry their provenance; none is written for this
repo (research R8). A library that breaks any rule below raises at start-up rather than shipping broken.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

DATA_FILE = Path(__file__).resolve().parent / "data" / "library.json"

# The four families and the OWASP LLM Top 10 category each maps to (FR-003, Principle VI).
FAMILIES: dict[str, dict[str, str]] = {
    "direct_injection": {"label": "Direct prompt injection", "owasp_category": "LLM01: Prompt Injection"},
    "system_prompt_leak": {"label": "System prompt leak", "owasp_category": "LLM07: System Prompt Leakage"},
    "tool_exfiltration": {"label": "Tool-mediated exfiltration", "owasp_category": "LLM06: Excessive Agency"},
    "indirect_injection": {"label": "Indirect injection via tool output", "owasp_category": "LLM01: Prompt Injection"},
}

ID_PATTERN = re.compile(r"^[a-z]{2,4}-\d{3}$")
MAX_PROMPT_CHARS = 4_000          # Principle VIII: plain conversation, never a flooding payload
MIN_PROMPTS, MAX_PROMPTS = 16, 24  # "about 20" in FR-001
MIN_PER_FAMILY = 3                 # FR-003
REQUIRED_TEXT_FIELDS = ("title", "text", "source", "source_url", "licence")


class LibraryError(Exception):
    """The library file is not usable. Raised at load time, never swallowed."""


@dataclass(frozen=True)
class AttackPrompt:
    id: str
    title: str
    text: str
    family: str
    owasp_category: str
    source: str
    source_url: str
    licence: str


@dataclass(frozen=True)
class AttackLibrary:
    version: str
    prompts: tuple[AttackPrompt, ...]

    def families(self) -> list[dict[str, Any]]:
        return [{"key": key, "label": meta["label"], "owasp_category": meta["owasp_category"],
                 "prompt_count": len(self.prompts_in(key))} for key, meta in FAMILIES.items()]

    def prompts_in(self, family: str) -> list[AttackPrompt]:
        if family not in FAMILIES:
            raise LookupError(f"No attack family {family!r}.")
        return [p for p in self.prompts if p.family == family]

    def pick(self, family: str, prompt_id: str | None = None,
             rng: random.Random | None = None) -> AttackPrompt:
        """With an id, that prompt; without one, uniformly at random from the family (FR-007, FR-008)."""
        candidates = self.prompts_in(family)
        if prompt_id is None:
            return (rng or random).choice(candidates)
        for candidate in candidates:
            if candidate.id == prompt_id:
                return candidate
        raise LookupError(f"No prompt {prompt_id!r} in family {family!r}.")

    @property
    def attacker_source(self) -> str:
        """What Principle III records as the attacker: a set of prompts, not a model (FR-005, FR-019)."""
        return f"library:{self.version}"


def _text(entry: Mapping[str, Any], field: str, where: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise LibraryError(f"{where}: {field} must be a non-empty string.")
    return value


def build_library(data: Mapping[str, Any]) -> AttackLibrary:
    """Validate a library and return it. Every rule in contracts/attack-library.md is checked here."""
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():                       # rule 1
        raise LibraryError("The library's version must be a non-empty string.")

    raw = data.get("prompts")
    if not isinstance(raw, list):
        raise LibraryError("The library's prompts must be a list.")

    prompts: list[AttackPrompt] = []
    seen_ids: set[str] = set()
    seen_text: set[str] = set()
    for position, entry in enumerate(raw):
        if not isinstance(entry, Mapping):
            raise LibraryError(f"Prompt at position {position} is not an object.")
        prompt_id = entry.get("id")
        if not isinstance(prompt_id, str) or not ID_PATTERN.match(prompt_id):     # rule 2
            raise LibraryError(f"Prompt at position {position} needs an identifier like 'spl-002', not {prompt_id!r}.")
        if prompt_id in seen_ids:
            raise LibraryError(f"The identifier {prompt_id!r} appears more than once.")
        seen_ids.add(prompt_id)

        where = f"Prompt {prompt_id}"
        family = entry.get("family")
        if family not in FAMILIES:                                                # rule 3
            raise LibraryError(f"{where}: {family!r} is not one of the four attack families.")
        expected = FAMILIES[family]["owasp_category"]
        if entry.get("owasp_category") != expected:                               # rule 4
            raise LibraryError(f"{where}: family {family!r} maps to OWASP category {expected!r}, "
                               f"not {entry.get('owasp_category')!r}.")
        values = {field: _text(entry, field, where) for field in REQUIRED_TEXT_FIELDS}  # rule 5
        if len(values["text"]) > MAX_PROMPT_CHARS:
            raise LibraryError(f"{where}: a prompt may be at most {MAX_PROMPT_CHARS} characters.")
        if values["text"] in seen_text:                                           # rule 8
            raise LibraryError(f"{where}: two prompts share the same text.")
        seen_text.add(values["text"])

        prompts.append(AttackPrompt(id=prompt_id, family=family, owasp_category=expected, **values))

    if not MIN_PROMPTS <= len(prompts) <= MAX_PROMPTS:                            # rule 7
        raise LibraryError(f"The library must hold between {MIN_PROMPTS} and {MAX_PROMPTS} prompts, "
                           f"not {len(prompts)}.")
    for family in FAMILIES:                                                       # rule 6
        count = sum(1 for p in prompts if p.family == family)
        if count < MIN_PER_FAMILY:
            raise LibraryError(f"Family {family!r} needs at least {MIN_PER_FAMILY} prompts, but has {count}.")

    return AttackLibrary(version=version, prompts=tuple(prompts))


def load_library(path: Path | None = None) -> AttackLibrary:
    path = DATA_FILE if path is None else Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise LibraryError(f"The attack library is missing: {path}") from None
    except json.JSONDecodeError as error:
        raise LibraryError(f"The attack library {path.name} is not valid JSON: {error}") from None
    try:
        return build_library(data)
    except LibraryError as error:
        raise LibraryError(f"The attack library {path.name} is not usable. {error}") from None


def families() -> Iterable[str]:
    return FAMILIES.keys()
