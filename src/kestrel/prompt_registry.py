"""Versioned prompt registry (feature 009).

The three model-facing prompts Kestrel sends to a model — the attacker prompt per family, the judge prompt and the
recommender (fix-advice) prompt — each have a stable id, a semantic version, their authored template text, and a
content fingerprint. The registry reads each prompt's authored text from the code that owns it
(`attack/attacker.py`, `judge/client.py`) — the single live source — and a committed lock
(`prompt_versions.lock.json`) pins the fingerprint of every `(id, version)` and the active version per id.

`verify_lock()` fails when a prompt's live text no longer matches the fingerprint the lock pins to its active
version, so a prompt cannot change without a version bump (FR-005, FR-006). No new dependency: `hashlib` and `re`
are standard library; the lock holds only ids, versions and fingerprints — never target secrets or attack-library
fixtures (FR-011, FR-012). The deterministic memory summariser has no model prompt and is not registered (three
kinds, see the spec Assumptions footnote).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from kestrel.attack.attacker import GOALS
from kestrel.attack.attacker import SYSTEM_PROMPT as _ATTACKER_SYSTEM_PROMPT
from kestrel.judge.client import RECOMMEND_SYSTEM_PROMPT as _RECOMMEND_SYSTEM_PROMPT
from kestrel.judge.client import SYSTEM_PROMPT as _JUDGE_SYSTEM_PROMPT

LOCK_PATH = Path(__file__).resolve().parent / "prompt_versions.lock.json"
# Non-active prompt versions live as plain template files beside the active prompts (feature 009 US4). The active
# version's text is the live code constant; every other registered version is a file `<id with ':'->'_'>@<ver>.txt`.
TEMPLATES_DIR = Path(__file__).resolve().parent / "prompt_templates"
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

JUDGE_ID = "judge"
RECOMMENDER_ID = "recommender"


class PromptNotRegistered(LookupError):
    """A prompt id or version the registry does not know; a run or arm naming it is refused (FR-009)."""


@dataclass(frozen=True)
class PromptEntry:
    """One registered prompt at its active version (FR-001). `text` is the authored template; `fingerprint` is
    sha256 of that text. Never carries a secret or a runtime-filled value."""

    id: str
    version: str
    text: str
    fingerprint: str


def attacker_id(family: str) -> str:
    return f"attacker:{family}"


def is_valid_version(version: str) -> bool:
    return bool(_VERSION_RE.match(version))


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _authored_texts() -> dict[str, str]:
    """The live authored template text of each registered prompt, keyed by id. The attacker entry per family is the
    system prompt with that family's (authored, static) goal filled in; runtime data (hints, conversation) and the
    shared DATA_RULE are never part of the versioned text (research D6, D7)."""
    texts = {attacker_id(family): _ATTACKER_SYSTEM_PROMPT.format(goal=goal) for family, goal in GOALS.items()}
    texts[JUDGE_ID] = _JUDGE_SYSTEM_PROMPT
    texts[RECOMMENDER_ID] = _RECOMMEND_SYSTEM_PROMPT
    return texts


def _lock() -> dict[str, dict]:
    """`{id: {"active": version, "versions": {version: fingerprint}}}` — committed, append-only (FR-005)."""
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def active_version(prompt_id: str) -> str:
    try:
        return _lock()[prompt_id]["active"]
    except KeyError as error:
        raise PromptNotRegistered(prompt_id) from error


def has(prompt_id: str, version: str) -> bool:
    entry = _lock().get(prompt_id)
    return bool(entry and version in entry.get("versions", {}))


def registry() -> list[PromptEntry]:
    """The active entry of every registered prompt, sorted by id (FR-001)."""
    lock = _lock()
    out: list[PromptEntry] = []
    for prompt_id, text in sorted(_authored_texts().items()):
        version = lock.get(prompt_id, {}).get("active", "0.0.0")
        out.append(PromptEntry(id=prompt_id, version=version, text=text, fingerprint=fingerprint(text)))
    return out


def _template_path(prompt_id: str, version: str) -> Path:
    return TEMPLATES_DIR / f"{prompt_id.replace(':', '_')}@{version}.txt"


def text_for(prompt_id: str, version: str) -> str:
    """The authored template text of a specific registered version. The active version is the live code constant; a
    non-active version is read from its template file beside the active prompts (feature 009 US4)."""
    if not has(prompt_id, version):
        raise PromptNotRegistered(f"{prompt_id}@{version}")
    if version == active_version(prompt_id):
        return _authored_texts()[prompt_id]
    path = _template_path(prompt_id, version)
    if not path.exists():
        raise PromptNotRegistered(f"{prompt_id}@{version}: no template file {path.name}")
    return path.read_text(encoding="utf-8")


def verify_lock() -> list[str]:
    """Ids that fail the guard (FR-005, FR-006). An id is reported when its live authored (active) text no longer
    matches the fingerprint pinned to its active version, when it has no lock entry, or when any registered version's
    resolved text (the active code text, or a non-active template file) does not match its pinned fingerprint — i.e.
    a prompt changed without a version bump. Empty list = clean."""
    lock = _lock()
    drifted: set[str] = set()
    for prompt_id, text in _authored_texts().items():   # every authored prompt is registered and matches its active
        entry = lock.get(prompt_id)
        if entry is None or entry.get("versions", {}).get(entry.get("active")) != fingerprint(text):
            drifted.add(prompt_id)
    for prompt_id, entry in lock.items():               # every registered (id, version) resolves and matches
        for version, recorded in entry.get("versions", {}).items():
            try:
                if fingerprint(text_for(prompt_id, version)) != recorded:
                    drifted.add(prompt_id)
            except PromptNotRegistered:
                drifted.add(prompt_id)
    return sorted(drifted)
