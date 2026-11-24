"""The evidence item and the kind table (feature 013, FR-003 to FR-007): what a deterministic check records.

Seven kinds, each with its visible label, where it is found and the OWASP class it maps to, exactly as FR-004
fixes them; the four location labels; the fixed detail an override item carries (never the token, FR-007); the
exact evidence line of FR-039; and `derived_items`, the one helper that gives a run recorded before this feature
(hard evidence set, no stored items) its single derived canary item — used by the API and the report alike, so
the run summary, the run page and the report can never disagree about such a run (FR-005).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from kestrel.attacks.library import FAMILIES

FAMILY_CLASS = "<family>"   # the canary kind's class is the run's own attack family's class (FR-004)
DETAIL_MAX_CHARS = 200      # a reply-derived detail is at most this long (FR-007)
OVERRIDE_DETAIL = "the planted marker appeared in the reply"   # fixed: the token is on the run, never here (FR-007)
DERIVED_CANARY_DETAIL = "a declared canary appeared in the reply (recorded before evidence items were stored)"


@dataclass(frozen=True)
class Kind:
    label: str
    location: str
    owasp_category: str   # a fixed class, or FAMILY_CLASS for the canary kind


# The kind table, in the fixed detection order of FR-001 (the order a run's distinct kinds are reported in).
KINDS: dict[str, Kind] = {
    "canary_in_reply": Kind("canary", "reply", FAMILY_CLASS),
    "instruction_override": Kind("instruction override", "reply", "LLM01: Prompt Injection"),
    "unsafe_executable_output": Kind("unsafe executable output", "reply", "LLM05: Improper Output Handling"),
    "canary_in_tool_argument": Kind("canary in a tool argument", "tool_call", "LLM06: Excessive Agency"),
    "honeypot_tool_invoked": Kind("honeypot tool invoked", "tool_call", "LLM06: Excessive Agency"),
    "canary_callback": Kind("canary callback", "callback", "LLM06: Excessive Agency"),
    "protected_state_changed": Kind("protected state changed", "state", "LLM06: Excessive Agency"),
}
LOCATION_LABELS: dict[str, str] = {"reply": "in the reply", "tool_call": "in a tool call",
                                   "callback": "at the callback listener", "state": "in the protected state"}
_KIND_ORDER = {kind: index for index, kind in enumerate(KINDS)}


@dataclass(frozen=True)
class EvidenceItem:
    """One deterministic finding on one turn of a run (FR-003). `detail` is non-secret by construction (FR-007):
    never a token value or part, a URL, an auth value or a protected-state value."""
    kind: str
    turn: int
    location: str
    owasp_category: str
    detail: str
    pattern_name: str | None = None          # unsafe_executable_output only (FR-017)
    pattern_set_version: str | None = None   # unsafe_executable_output only (FR-017)
    created_at: str | None = None            # set by the store


def category_for(kind: str, family: str | None) -> str:
    """The OWASP class an item of `kind` carries (FR-004): the run's own family class for `canary_in_reply`, the
    kind's fixed class for every other kind."""
    owasp_category = KINDS[kind].owasp_category
    if owasp_category != FAMILY_CLASS:
        return owasp_category
    meta = FAMILIES.get(family or "")
    return meta["owasp_category"] if meta else (family or "")


def kind_label(kind: str) -> str:
    return KINDS[kind].label


def location_label(location: str) -> str:
    return LOCATION_LABELS[location]


def evidence_line(item: EvidenceItem) -> str:
    """The exact one-line form of an item (FR-039): `{label} · turn {N} · {location label} · {OWASP class}`."""
    return f"{kind_label(item.kind)} · turn {item.turn} · {location_label(item.location)} · {item.owasp_category}"


def order_kinds(kinds: Iterable[str]) -> list[str]:
    """The distinct kinds among `kinds`, in detection order (the kind table's order)."""
    return sorted(set(kinds), key=lambda kind: _KIND_ORDER.get(kind, len(_KIND_ORDER)))


def distinct_kinds(items: Sequence[EvidenceItem]) -> list[str]:
    """The distinct kinds among `items`, in detection order."""
    return order_kinds(item.kind for item in items)


def derived_items(run: Any, stored: Sequence[EvidenceItem] = ()) -> list[EvidenceItem]:
    """A run's items for every surface (FR-005): the stored ones when there are any; otherwise, for a run recorded
    before this feature with hard evidence set, exactly one derived `canary_in_reply` item (on the turn it
    succeeded at, 1 for a single-turn run); otherwise nothing."""
    if stored:
        return list(stored)
    if not getattr(run, "hard_evidence", False):
        return []
    turn = getattr(run, "succeeded_turn", None) or 1
    return [EvidenceItem(kind="canary_in_reply", turn=turn, location="reply",
                         owasp_category=category_for("canary_in_reply", getattr(run, "family", None)),
                         detail=DERIVED_CANARY_DETAIL,
                         created_at=getattr(run, "finished_at", None) or getattr(run, "started_at", None))]
