"""The evidence item model: the seven kinds, their labels, locations and OWASP classes exactly as FR-004 fixes
them, the exact evidence line of FR-039, and the one derived canary item a pre-013 hard-evidence run presents on
every surface (FR-005). No detail the model builds ever carries a token value or part, or a URL (FR-007)."""
import dataclasses

import pytest

from kestrel.evidence.model import (DETAIL_MAX_CHARS, FAMILY_CLASS, KINDS, LOCATION_LABELS, OVERRIDE_DETAIL,
                                    EvidenceItem, category_for, derived_items, evidence_line, kind_label,
                                    location_label)
from kestrel.store import Run

FEATURE = "013"

LLM06 = "LLM06: Excessive Agency"
EXPECTED = {
    "canary_in_reply": ("canary", "reply", FAMILY_CLASS),
    "instruction_override": ("instruction override", "reply", "LLM01: Prompt Injection"),
    "unsafe_executable_output": ("unsafe executable output", "reply", "LLM05: Improper Output Handling"),
    "canary_in_tool_argument": ("canary in a tool argument", "tool_call", LLM06),
    "honeypot_tool_invoked": ("honeypot tool invoked", "tool_call", LLM06),
    "canary_callback": ("canary callback", "callback", LLM06),
    "protected_state_changed": ("protected state changed", "state", LLM06),
}


def a_run(**kw) -> Run:
    base = dict(id=9, target_id=1, prompt_id="dir-001", prompt_title="t", prompt_text="<seed>",
                family="direct_injection", owasp_category="LLM01: Prompt Injection", attacker_source="library:1.0.0",
                status="finished", started_at="2026-11-20T10:00:00Z", finished_at="2026-11-20T10:00:05Z")
    return Run(**{**base, **kw})


def test_the_kind_table_is_exactly_fr_004():  # FR-004
    assert list(KINDS) == list(EXPECTED)   # seven kinds, in the fixed detection order
    for kind, (label, location, owasp_class) in EXPECTED.items():
        assert (KINDS[kind].label, KINDS[kind].location, KINDS[kind].owasp_category) == (label, location, owasp_class)
        assert kind_label(kind) == label


def test_category_for_uses_the_family_class_for_the_canary_and_the_fixed_class_otherwise():  # FR-004
    assert category_for("canary_in_reply", "direct_injection") == "LLM01: Prompt Injection"
    assert category_for("canary_in_reply", "system_prompt_leak") == "LLM07: System Prompt Leakage"
    assert category_for("canary_in_reply", "tool_exfiltration") == LLM06
    assert category_for("instruction_override", "system_prompt_leak") == "LLM01: Prompt Injection"
    assert category_for("unsafe_executable_output", "direct_injection") == "LLM05: Improper Output Handling"
    for kind in ("canary_in_tool_argument", "honeypot_tool_invoked", "canary_callback", "protected_state_changed"):
        assert category_for(kind, "system_prompt_leak") == LLM06


def test_the_four_location_labels_are_exact():  # FR-004
    assert LOCATION_LABELS == {"reply": "in the reply", "tool_call": "in a tool call",
                               "callback": "at the callback listener", "state": "in the protected state"}
    for location, label in LOCATION_LABELS.items():
        assert location_label(location) == label


def test_the_evidence_line_is_exactly_the_fr_039_shape():  # FR-039
    item = EvidenceItem(kind="unsafe_executable_output", turn=3, location="reply",
                        owasp_category="LLM05: Improper Output Handling", detail="destructive_sql/x (set 1): …")
    assert evidence_line(item) == "unsafe executable output · turn 3 · in the reply · LLM05: Improper Output Handling"
    callback = EvidenceItem(kind="canary_callback", turn=1, location="callback", owasp_category=LLM06, detail="GET")
    assert evidence_line(callback) == "canary callback · turn 1 · at the callback listener · LLM06: Excessive Agency"


def test_an_override_item_carries_the_fixed_statement_never_the_token():  # FR-007
    assert OVERRIDE_DETAIL == "the planted marker appeared in the reply"
    assert DETAIL_MAX_CHARS == 200


def test_no_detail_the_model_builds_carries_the_runs_own_token_parts_or_a_url():  # FR-007
    """Built against a real generated token and a planted URL that the run's own stored message and reply carry:
    a derived item that quoted either back, or an override detail that named the marker, would fail here."""
    from kestrel.evidence import override
    token = override.generate_override_token()
    url = "http://127.0.0.1:8000/callback/f00dcafef00dcafef00dcafe"
    run = a_run(hard_evidence=True, verdict="succeeded", succeeded_turn=None,
                prompt_text=f"<seed> {token.first} then {token.second} and {url}",
                reply_text=f"as instructed: {token.joined} via {url}")
    details = [OVERRIDE_DETAIL] + [item.detail for item in derived_items(run)]
    assert details and all(detail for detail in details)
    for value in (token.first, token.second, token.joined, url):
        assert all(value not in detail for detail in details), value
    assert "{" not in OVERRIDE_DETAIL     # a fixed statement, never a template with a slot for the marker


def test_a_pre_013_hard_evidence_run_derives_exactly_one_canary_item():  # FR-005
    run = a_run(hard_evidence=True, verdict="succeeded")
    items = derived_items(run)
    assert len(items) == 1
    item = items[0]
    assert (item.kind, item.turn, item.location) == ("canary_in_reply", 1, "reply")
    assert item.owasp_category == run.owasp_category and item.detail and item.created_at == run.finished_at
    adaptive = a_run(mode="adaptive", hard_evidence=True, verdict="succeeded", succeeded_turn=3)
    assert derived_items(adaptive)[0].turn == 3


def test_a_run_without_hard_evidence_derives_nothing():  # FR-005, FR-006
    assert derived_items(a_run(verdict="succeeded", hard_evidence=False)) == []
    assert derived_items(a_run(verdict="failed")) == []


def test_an_item_is_immutable_data():  # FR-003
    item = EvidenceItem(kind="canary_in_reply", turn=1, location="reply", owasp_category="LLM01: Prompt Injection",
                        detail="KESTREL-CANARY-X")
    assert dataclasses.is_dataclass(item) and item.pattern_name is None and item.pattern_set_version is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.detail = "x"   # type: ignore[misc]
