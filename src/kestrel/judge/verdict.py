"""The judge's answer shape and the fix-advice shape, validated with Pydantic (contracts/judge.md, FR-017, FR-021).

The model is asked for structured JSON; we validate it against a Pydantic model and never coerce a stray value: a
confident wrong verdict is worse than an honest "unclear". ``RESPONSE_SCHEMA`` / ``RECOMMEND_SCHEMA`` are derived
from the models with ``model_json_schema()``, so the schema we ask the model for and the shape we then accept can
never drift apart. A validation failure carries the error, so the caller can show the model exactly what to fix.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

VERDICTS = ("succeeded", "failed", "unclear")
MAX_REASON_CHARS = 300
MAX_RECOMMENDATION_CHARS = 1_000
NO_REASON = "The judge gave no reason."


class Verdict(BaseModel):
    """The judge's structured answer. ``progress`` is required but nullable: single-turn runs send ``null``."""
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["succeeded", "failed", "unclear"]
    reason: str = Field(max_length=MAX_REASON_CHARS)
    progress: str | None


class Recommendation(BaseModel):
    """One concrete fix suggestion derived from non-secret inputs only (feature 005, FR-012)."""
    model_config = ConfigDict(extra="forbid")
    recommendation: str = Field(max_length=MAX_RECOMMENDATION_CHARS)


class VerdictParseError(Exception):
    """The judge's answer could not be validated against the schema (FR-021)."""


_STRIP_KEYS = ("title", "description", "default", "examples", "maxLength", "minLength", "pattern", "format")


def _strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Derive an OpenAI-strict-compatible JSON schema from ``model``.

    ``model_json_schema()`` is the single source of truth; we only drop keywords providers reject in strict mode
    (string length, pattern, format, titles) and express a nullable field as ``type: [T, "null"]`` instead of
    ``anyOf``. ``extra="forbid"`` already yields ``additionalProperties: false`` and lists every field in
    ``required`` (no field has a default), which is what strict structured output needs.
    """
    def clean(node: Any) -> Any:
        if isinstance(node, list):
            return [clean(item) for item in node]
        if not isinstance(node, dict):
            return node
        node = {key: value for key, value in node.items() if key not in _STRIP_KEYS}
        choices = node.get("anyOf")
        if isinstance(choices, list) and choices and all(isinstance(c, dict) and set(c) <= {"type"} for c in choices):
            types = [c["type"] for c in choices if "type" in c]
            if "null" in types and len(types) >= 2:
                node = {key: value for key, value in node.items() if key != "anyOf"}
                node["type"] = types
        return {key: clean(value) for key, value in node.items()}

    return clean(model.model_json_schema())


RESPONSE_SCHEMA = _strict_schema(Verdict)
RECOMMEND_SCHEMA = _strict_schema(Recommendation)


@dataclass(frozen=True)
class ParsedVerdict:
    verdict: str
    reason: str
    progress: str | None = None  # the adaptive "how close" note (feature 003); None for single-turn
    tokens: int = 0              # tokens the judge call used, for the adaptive token budget (R7)


def _one_line(text: str | None) -> str:
    collapsed = " ".join((text or "").split()).strip()
    if not collapsed:
        return NO_REASON
    return collapsed[:MAX_REASON_CHARS]


def _first_json_object(text: str) -> Any | None:
    """The first decodable JSON object in free text (a preamble, a code fence, trailing prose), or None.

    Models sometimes wrap the object in a sentence or a ```json fence even when asked not to; raw_decode reads
    the whole object from each ``{``, so a leading sentence or a ``}`` inside a string cannot defeat it."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def validate_verdict(content: str) -> Verdict:
    """Validate the model's answer against :class:`Verdict`, tolerating a preamble around the JSON object.

    Raises :class:`VerdictParseError` carrying the validation message, so the caller can retry with that as
    feedback (judge item 1). The caller turns a final failure into an honest "unclear" run (FR-021)."""
    try:
        return Verdict.model_validate_json(content)
    except ValidationError as first_error:
        obj = _first_json_object(content)
        if obj is None:
            raise VerdictParseError(str(first_error)) from first_error
        try:
            return Verdict.model_validate(obj)
        except ValidationError as error:
            raise VerdictParseError(str(error)) from error


def validate_recommendation(content: str) -> Recommendation:
    """Validate a fix suggestion against :class:`Recommendation`, tolerating a preamble (same rule as verdicts)."""
    try:
        return Recommendation.model_validate_json(content)
    except ValidationError as first_error:
        obj = _first_json_object(content)
        if obj is None:
            raise VerdictParseError(str(first_error)) from first_error
        try:
            return Recommendation.model_validate(obj)
        except ValidationError as error:
            raise VerdictParseError(str(error)) from error


def parse_verdict(answer: Any) -> ParsedVerdict:
    """Validate ``answer`` (a dict, or a JSON string) and normalise it for display. Raises VerdictParseError."""
    try:
        model = Verdict.model_validate(answer) if isinstance(answer, dict) else validate_verdict(answer)
    except ValidationError as error:
        raise VerdictParseError(str(error)) from error
    progress = _one_line(model.progress) if model.progress and model.progress.strip() else None
    return ParsedVerdict(verdict=model.verdict, reason=_one_line(model.reason), progress=progress)
