"""The judge's answer shape, and reading it strictly (contracts/judge.md, FR-017, FR-021).

A verdict string outside the three values is a parse failure, never coerced: a confident wrong verdict is
worse than an honest "unclear".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

VERDICTS = ("succeeded", "failed", "unclear")
MAX_REASON_CHARS = 200
NO_REASON = "The judge gave no reason."

# The JSON schema asked of the model (OpenAI-compatible structured output, R3). `progress` is the adaptive
# "how close" note (feature 003, R6); single-turn runs ignore it, so it is optional.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "reason": {"type": "string"},
        "progress": {"type": "string"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}


class VerdictParseError(Exception):
    """The judge's answer could not be read as a verdict (FR-021)."""


@dataclass(frozen=True)
class ParsedVerdict:
    verdict: str
    reason: str
    progress: str | None = None  # the adaptive "how close" note (feature 003); None for single-turn


def _one_line(text: str) -> str:
    collapsed = " ".join(text.split()).strip()
    if not collapsed:
        return NO_REASON
    return collapsed[:MAX_REASON_CHARS]


def _from_mapping(data: object) -> ParsedVerdict:
    if not isinstance(data, dict):
        raise VerdictParseError("The judge's answer was not a JSON object.")
    verdict = data.get("verdict")
    if verdict not in VERDICTS:
        raise VerdictParseError(f"The judge returned {verdict!r}, which is not one of {VERDICTS}.")
    if "reason" not in data or not isinstance(data["reason"], str):
        raise VerdictParseError("The judge's answer had no reason string.")
    raw_progress = data.get("progress")
    progress = _one_line(raw_progress) if isinstance(raw_progress, str) and raw_progress.strip() else None
    return ParsedVerdict(verdict=verdict, reason=_one_line(data["reason"]), progress=progress)


def parse_verdict(answer: object) -> ParsedVerdict:
    """Read a verdict from a dict (structured output) or a string (its first JSON object), or raise (R3)."""
    if isinstance(answer, dict):
        return _from_mapping(answer)
    if not isinstance(answer, str):
        raise VerdictParseError(f"The judge's answer was {type(answer).__name__}, not text or an object.")

    # A clean string first, then the first {...} block embedded in prose or a code fence.
    try:
        return _from_mapping(json.loads(answer))
    except (json.JSONDecodeError, VerdictParseError):
        pass
    for match in re.finditer(r"\{.*?\}", answer, re.DOTALL):
        try:
            return _from_mapping(json.loads(match.group(0)))
        except (json.JSONDecodeError, VerdictParseError):
            continue
    raise VerdictParseError("No readable verdict was found in the judge's answer.")
