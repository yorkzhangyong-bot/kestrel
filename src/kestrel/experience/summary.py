"""The one-line situation summary written to a memory record (FR-008, FR-013).

Built only from the run's own per-turn judge progress notes — no model call. Sanitised to a fixed, bounded,
single line so instruction-like text cannot ride memory into the attacker's prompt (no self-injection).
"""
from __future__ import annotations

import re
from typing import Iterable

MAX_SUMMARY_CHARS = 280


def build_summary(progress_notes: Iterable[str | None], *, family: str, verdict: str | None,
                  hard_evidence: bool, turns_used: int | None, stopping_condition: str | None) -> str:
    """Join the judge progress notes into one sanitised line; fall back to run metadata when there are none."""
    notes = [note.strip() for note in progress_notes if note and note.strip()]
    if notes:
        text = " · ".join(notes)
    else:
        turns = turns_used if turns_used is not None else 1
        text = f"{family}: {verdict or 'unclear'} after {turns} turn(s)"
        if stopping_condition:  # omit the clause entirely when there is no stopping condition (never "n/a")
            text += f"; stopped at {stopping_condition}"
        if hard_evidence:
            text += "; canary hard evidence"
    return _sanitise(text)


def _sanitise(text: str) -> str:
    """One line, no control characters, bounded length, truncated at a word boundary (FR-013)."""
    mapped = "".join(ch if (ch == " " or ch.isprintable()) else " " for ch in text)
    collapsed = re.sub(r"\s+", " ", mapped).strip()
    if len(collapsed) <= MAX_SUMMARY_CHARS:
        return collapsed
    # Keep the 280-char cap, but cut back to the last whole word and mark the trim with an ellipsis.
    clipped = collapsed[:MAX_SUMMARY_CHARS - 1]
    space = clipped.rfind(" ")
    if space > 0:
        clipped = clipped[:space]
    return clipped.rstrip() + "…"
