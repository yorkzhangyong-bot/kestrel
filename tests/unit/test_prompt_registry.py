"""The prompt registry: three kinds at 1.0.0, has/text_for, version shape (009/FR-001, 009/FR-002, 009/FR-009)."""
import pytest

from kestrel import prompt_registry as pr

FEATURE = "009"

EXPECTED_IDS = {
    "attacker:direct_injection",
    "attacker:system_prompt_leak",
    "attacker:tool_exfiltration",
    "attacker:indirect_injection",
    "judge",
    "recommender",
}


def test_registry_lists_the_three_kinds_at_1_0_0():  # 009/FR-001, 009/FR-002
    entries = pr.registry()
    assert {e.id for e in entries} == EXPECTED_IDS
    assert all(e.version == "1.0.0" for e in entries)
    assert all(e.text and e.fingerprint == pr.fingerprint(e.text) for e in entries)


def test_no_summariser_prompt_is_registered():  # 009 — three model-facing kinds only
    assert not any("summar" in e.id for e in pr.registry())


def test_has_and_active_version():  # 009/FR-009
    assert pr.has("judge", "1.0.0")
    assert not pr.has("judge", "9.9.9")
    assert not pr.has("attacker:nope", "1.0.0")
    assert pr.active_version("judge") == "1.0.0"
    with pytest.raises(pr.PromptNotRegistered):
        pr.active_version("attacker:nope")


def test_text_for_returns_the_active_text():  # 009/FR-001
    entry = next(e for e in pr.registry() if e.id == "judge")
    assert pr.text_for("judge", "1.0.0") == entry.text


def test_text_for_unknown_is_refused():  # 009/FR-009
    with pytest.raises(pr.PromptNotRegistered):
        pr.text_for("judge", "2.0.0")
    with pytest.raises(pr.PromptNotRegistered):
        pr.text_for("recommender", "nope")


def test_version_shape_is_validated():  # 009/FR-005
    assert pr.is_valid_version("1.0.0")
    assert pr.is_valid_version("12.3.45")
    assert not pr.is_valid_version("1.0")
    assert not pr.is_valid_version("v1.0.0")
    assert not pr.is_valid_version("1.0.0-rc1")
