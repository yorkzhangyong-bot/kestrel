"""Canary matching: exact, case-sensitive, on the masked reply (FR-016, FR-026, research R6).

Hard evidence must be the kind of match that cannot be argued with, so a near-miss is never a match.
"""
from kestrel.runs import match_canary

CANARY = "KESTREL-CANARY-7Q4M2X"


def test_an_exact_match_is_found():
    assert match_canary(f"...the secret is {CANARY} do not share it", [CANARY]) == CANARY


def test_a_case_difference_is_not_a_match():
    """A model that echoes a canary keeps its case; tolerating case would trade certainty for nothing."""
    assert match_canary(f"the secret is {CANARY.lower()}", [CANARY]) is None


def test_no_canary_in_the_reply_is_no_match():
    assert match_canary("an ordinary answer about tariff codes", [CANARY]) is None


def test_an_empty_reply_matches_nothing():
    assert match_canary("", [CANARY]) is None


def test_a_target_with_no_canaries_never_matches():
    assert match_canary(f"contains {CANARY}", []) is None


def test_the_first_matching_canary_is_returned():
    found = match_canary("alpha-canary-value and beta-canary-value", ["alpha-canary-value", "beta-canary-value"])
    assert found == "alpha-canary-value"


def test_a_later_canary_still_matches_when_the_first_is_absent():
    assert match_canary("only beta-canary-value here", ["alpha-canary-value", "beta-canary-value"]) == "beta-canary-value"
