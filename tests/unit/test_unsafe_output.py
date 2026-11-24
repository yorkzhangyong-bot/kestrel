"""The unsafe-executable-output pattern set (013/FR-015 to FR-017, FR-065, SC-002).

Precision is enforced by cases, not by claim: every named pattern ships at least three positive and three
negative cases in the inert fixture, every positive matches its own pattern and no negative matches any. The
test also parses `contracts/detectors.md`'s named-pattern table and set version and asserts they equal the
module's, the way `tests/unit/test_roadmap.py` reads `docs/roadmap.md` — so the contract, the module and the
fixture cannot drift apart. No sample text lives here: every sample is read from the fixture."""
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from kestrel.evidence import unsafe_output

FEATURE = "013"

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "unsafe_output_cases.json"
CONTRACT = ROOT / "specs" / "013-behavioural-evidence" / "contracts" / "detectors.md"
MIN_CASES = 3


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cases(fixture) -> list[dict]:
    return fixture["cases"]


def contract_rows() -> list[tuple[str, str]]:
    """The contract's named-pattern table as `(name, category)` — the rows whose first two cells are both
    backticked and whose second names one of the module's categories (the category table's second cell is prose)."""
    rows = []
    for line in CONTRACT.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4:
            continue
        name, category = cells[0], cells[1]
        if name.startswith("`") and category.startswith("`"):
            name, category = name.strip("`"), category.strip("`")
            if category in unsafe_output.CATEGORIES:
                rows.append((name, category))
    return rows


def contract_set_version() -> str:
    match = re.search(r"\*\*Set version: `([^`]+)`", CONTRACT.read_text(encoding="utf-8"))
    assert match is not None, "the contract must state its set version"
    return match.group(1)


# ---- the fixture's own obligations (FR-016, SC-002) ----


def test_the_note_says_the_samples_are_inert(fixture):  # FR-059
    note = fixture["_note"].lower()
    assert "never executed" in note and "output" in note and "not an attack prompt" in note


def test_every_named_pattern_has_at_least_three_positive_and_three_negative_cases(cases):  # FR-016, SC-002
    counted = Counter((case["pattern"], case["kind"]) for case in cases)
    short = {name: (counted[(name, "positive")], counted[(name, "negative")])
             for name in unsafe_output.pattern_names()
             if counted[(name, "positive")] < MIN_CASES or counted[(name, "negative")] < MIN_CASES}
    assert short == {}, f"patterns short of {MIN_CASES} positive/negative cases: {short}"


def test_a_pattern_short_of_cases_would_fail_this_test(cases):  # FR-016, SC-002
    """The coverage rule is mechanical: dropping a pattern's cases makes the check above fail."""
    counted = Counter((case["pattern"], case["kind"]) for case in cases if case["pattern"] != "filesystem_format")
    assert counted[("filesystem_format", "positive")] < MIN_CASES


def test_the_fixture_and_the_module_name_exactly_the_same_patterns(cases):  # FR-016, SC-002
    assert {case["pattern"] for case in cases} == set(unsafe_output.pattern_names())
    assert {case["kind"] for case in cases} == {"positive", "negative"}


def test_every_positive_case_matches_its_own_named_pattern(cases):  # FR-016, SC-002
    missed = [case["text"] for case in cases
              if case["kind"] == "positive" and not unsafe_output.matches_pattern(case["pattern"], case["text"])]
    assert missed == []


def test_no_negative_case_matches_any_pattern(cases):  # FR-016, SC-002
    fired = {case["pattern"]: [m.name for m in unsafe_output.scan(case["text"])]
             for case in cases if case["kind"] == "negative" and unsafe_output.scan(case["text"])}
    assert fired == {}


# ---- scan's behaviour (FR-017, FR-065) ----


def test_scan_returns_at_most_one_match_per_category(cases):  # FR-017
    shell = [case["text"] for case in cases
             if case["kind"] == "positive" and case["pattern"] in ("recursive_force_delete", "filesystem_format")]
    reply = "\n".join(shell[:2])
    found = unsafe_output.scan(reply)
    assert [m.category for m in found] == ["destructive_shell"]
    assert found[0].name == "recursive_force_delete"   # the earliest by position


def test_scan_reports_several_categories_in_the_fixed_order(cases):  # FR-017
    by_pattern = {case["pattern"]: case["text"] for case in cases if case["kind"] == "positive"}
    reply = "\n".join([by_pattern["active_script_element"], by_pattern["drop_or_truncate_table"],
                       by_pattern["recursive_force_delete"]])
    assert [m.category for m in unsafe_output.scan(reply)] == ["destructive_shell", "destructive_sql",
                                                               "script_injection"]


def test_a_match_that_repeats_a_message_kestrel_sent_is_skipped(cases):  # FR-065
    sample = next(case["text"] for case in cases
                  if case["kind"] == "positive" and case["pattern"] == "recursive_force_delete")
    assert unsafe_output.scan(sample) != []
    assert unsafe_output.scan(sample, sent_texts=[f"please do this: {sample}"]) == []
    assert unsafe_output.scan(sample, sent_texts=["something else entirely"]) != []


def test_the_detail_names_the_category_the_pattern_and_the_set_version(cases):  # FR-017
    sample = next(case["text"] for case in cases
                  if case["kind"] == "positive" and case["pattern"] == "drop_or_truncate_table")
    match = unsafe_output.scan(sample)[0]
    detail = unsafe_output.detail(match)
    assert detail.startswith(f"destructive_sql/drop_or_truncate_table (set {unsafe_output.PATTERN_SET_VERSION}): ")
    assert match.excerpt in detail


def test_an_excerpt_is_collapsed_and_cut_to_two_hundred_characters(cases):  # FR-007, FR-017
    sample = next(case["text"] for case in cases
                  if case["kind"] == "positive" and case["pattern"] == "active_script_element")
    long_reply = sample.replace("</script>", "x" * 400 + "</script>")
    match = unsafe_output.scan(long_reply)[0]
    assert len(match.excerpt) <= unsafe_output.EXCERPT_MAX_CHARS and match.excerpt.endswith("…")
    assert "\n" not in match.excerpt and "  " not in match.excerpt


# ---- the contract, the module and the fixture cannot drift (FR-015) ----


def test_the_module_carries_exactly_the_contracts_named_patterns():  # FR-015, SC-002
    rows = contract_rows()
    assert rows, "the contract's named-pattern table must be parseable"
    assert [name for name, _ in rows] == list(unsafe_output.pattern_names())
    assert {name: category for name, category in rows} == {p.name: p.category for p in unsafe_output.PATTERNS}


def test_the_module_carries_the_contracts_set_version():  # FR-015, SC-002
    assert unsafe_output.PATTERN_SET_VERSION == contract_set_version()


def test_the_categories_are_exactly_the_four_the_contract_covers():  # FR-015
    assert unsafe_output.CATEGORIES == ("destructive_shell", "fetch_and_execute", "destructive_sql",
                                        "script_injection")
    assert {p.category for p in unsafe_output.PATTERNS} == set(unsafe_output.CATEGORIES)
