"""The judge's answer and fix-advice shapes, validated with Pydantic (contracts/judge.md, FR-017, FR-021).

A verdict outside the three values, an extra field, or an over-long reason is a validation failure, never coerced
to the nearest match: a confident wrong verdict is worse than an honest "unclear".
"""
import json

import pytest
from pydantic import ValidationError

from kestrel.judge.verdict import (MAX_REASON_CHARS, RECOMMEND_SCHEMA, RESPONSE_SCHEMA, ParsedVerdict,
                                   Recommendation, Verdict, VerdictParseError, parse_verdict, validate_verdict)

FEATURE = "002"

REASON = "The agent refused and continued with its classification task."


# --- the derived schemas (judge item 1): the asked-for schema can't drift from the validated model ---

def test_every_response_schema_property_is_required():
    assert set(RESPONSE_SCHEMA["required"]) == set(RESPONSE_SCHEMA["properties"])  # verdict, reason, progress
    assert RESPONSE_SCHEMA["additionalProperties"] is False                        # extra=forbid


def test_every_recommend_schema_property_is_required():
    assert set(RECOMMEND_SCHEMA["required"]) == set(RECOMMEND_SCHEMA["properties"])
    assert RECOMMEND_SCHEMA["additionalProperties"] is False


def test_the_derived_schema_drops_keywords_providers_reject_in_strict_mode():
    blob = json.dumps(RESPONSE_SCHEMA)
    for banned in ("maxLength", "minLength", "pattern", "format", "title"):
        assert banned not in blob


# --- the Verdict model ---

def test_a_clean_answer_validates():
    model = Verdict.model_validate({"verdict": "failed", "reason": REASON, "progress": None})
    assert model.verdict == "failed" and model.reason == REASON and model.progress is None


@pytest.mark.parametrize("verdict", ["succeeded", "failed", "unclear"])
def test_each_of_the_three_verdicts_is_accepted(verdict):
    assert Verdict.model_validate({"verdict": verdict, "reason": "x", "progress": None}).verdict == verdict


def test_a_verdict_outside_the_three_values_is_rejected():
    for bad in ("success", "SUCCEEDED", "yes", "maybe", ""):
        with pytest.raises(ValidationError):
            Verdict.model_validate({"verdict": bad, "reason": "x", "progress": None})


def test_an_extra_field_is_rejected():
    with pytest.raises(ValidationError):
        Verdict.model_validate({"verdict": "failed", "reason": "x", "progress": None, "sneaky": 1})


def test_progress_is_required_but_may_be_null():
    assert Verdict.model_validate({"verdict": "failed", "reason": "x", "progress": None}).progress is None
    assert Verdict.model_validate({"verdict": "failed", "reason": "x", "progress": "wavered"}).progress == "wavered"
    with pytest.raises(ValidationError):   # the key must be present, even if null
        Verdict.model_validate({"verdict": "failed", "reason": "x"})


def test_a_reason_at_the_limit_is_accepted_but_over_it_is_rejected():
    Verdict.model_validate({"verdict": "failed", "reason": "x" * MAX_REASON_CHARS, "progress": None})
    with pytest.raises(ValidationError):
        Verdict.model_validate({"verdict": "failed", "reason": "x" * (MAX_REASON_CHARS + 1), "progress": None})


# --- validate_verdict: strict JSON with preamble tolerance, raising VerdictParseError for the retry loop ---

def test_a_bare_json_string_validates():
    assert validate_verdict('{"verdict": "unclear", "reason": "ambiguous", "progress": null}').verdict == "unclear"


def test_a_preamble_or_fence_around_the_object_is_tolerated():
    raw = 'Here is the JSON:\n```json\n{"verdict": "succeeded", "reason": "Canary echoed.", "progress": null}\n```'
    assert validate_verdict(raw).verdict == "succeeded"


def test_text_with_no_valid_object_raises_verdict_parse_error():
    with pytest.raises(VerdictParseError):
        validate_verdict("I think it probably did not work, but it is hard to say.")


def test_a_schema_violation_in_the_object_raises_verdict_parse_error():
    with pytest.raises(VerdictParseError):
        validate_verdict('{"verdict": "nope", "reason": "x", "progress": null}')


# --- parse_verdict convenience (display normalisation) ---

def test_parse_verdict_normalises_whitespace_and_blank_progress():
    parsed = parse_verdict({"verdict": "failed", "reason": "  held   the   line  ", "progress": "   "})
    assert isinstance(parsed, ParsedVerdict)
    assert parsed.verdict == "failed" and parsed.reason == "held the line" and parsed.progress is None


def test_parse_verdict_raises_on_a_bad_verdict():
    with pytest.raises(VerdictParseError):
        parse_verdict({"verdict": "worked", "reason": "x", "progress": None})


# --- Recommendation model ---

def test_recommendation_validates_and_forbids_extra():
    assert Recommendation.model_validate({"recommendation": "Refuse to reveal the prompt."}).recommendation
    with pytest.raises(ValidationError):
        Recommendation.model_validate({"recommendation": "x", "extra": 1})
