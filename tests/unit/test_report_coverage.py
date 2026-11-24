"""build_report OWASP coverage: the three tested classes with honest counts, the seven untested with reasons.

US3, FR-006/007/008, SC-005. Counts join on the run's owasp_category, which matches the attack library's labels.
"""
from kestrel.report.model import build_report
from kestrel.store import Run

FEATURE = "005"

NOW = "2026-10-28T12:00:00Z"
TESTED = {"LLM01: Prompt Injection", "LLM06: Excessive Agency", "LLM07: System Prompt Leakage"}


def run(**kw) -> Run:
    base = dict(id=1, target_id=1, prompt_id="p", prompt_title="t", prompt_text="<seed>",
                family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                attacker_source="library:1.0.0", status="finished", started_at=NOW, finished_at=NOW)
    return Run(**{**base, **kw})


class Target:
    name = "My agent"
    description = "a customs assistant"


def a_report(runs):
    return build_report(target=Target(), runs=runs, turns_by_run={}, recommendations={}, now=NOW)


def test_coverage_lists_exactly_the_three_tested_classes_with_counts():
    runs = [run(id=1, family="direct_injection", owasp_category="LLM01: Prompt Injection",
                verdict="succeeded", hard_evidence=True, reply_text="KESTREL-CANARY-9Z"),
            run(id=2, family="indirect_injection", owasp_category="LLM01: Prompt Injection", verdict="failed"),
            run(id=3, family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage", verdict="failed")]
    rows = {r.owasp_class: r for r in a_report(runs).coverage}
    assert TESTED <= set(rows)                                             # the three attack-family classes
    assert rows["LLM01: Prompt Injection"].run_count == 2                  # both injection families count here
    assert "injection" in rows["LLM01: Prompt Injection"].families.lower()
    assert rows["LLM07: System Prompt Leakage"].run_count == 1


def test_a_class_with_no_runs_says_not_run_yet():
    rows = {r.owasp_class: r for r in a_report([run(id=1, verdict="failed")]).coverage}
    assert rows["LLM06: Excessive Agency"].run_count == 0                  # no tool-exfiltration run
    assert rows["LLM06: Excessive Agency"].result == "not run yet"


def test_a_canary_success_is_confirmed_a_judge_success_is_suspected():
    confirmed = run(id=1, owasp_category="LLM07: System Prompt Leakage", verdict="succeeded",
                    hard_evidence=True, reply_text="KESTREL-CANARY-9Z")
    suspected = run(id=2, family="tool_exfiltration", owasp_category="LLM06: Excessive Agency",
                    verdict="succeeded", hard_evidence=False, reason="the judge thought it leaked")
    rows = {r.owasp_class: r for r in a_report([confirmed, suspected]).coverage}
    assert "confirmed" in rows["LLM07: System Prompt Leakage"].result     # hard evidence (Principle II)
    assert "suspected" in rows["LLM06: Excessive Agency"].result          # judge-only


def test_every_untested_class_carries_a_reason():
    # Feature 013 moved LLM05 out of this list (the detector covers it); the count is asserted below.
    assert all(u.reason.strip() for u in a_report([run(id=1, verdict="failed")]).untested)


# ---- feature 013: the detector's own row, and confirmed counted from the run's own items (013/FR-045) ----

from kestrel.evidence.model import EvidenceItem   # noqa: E402  (feature 013; the module's imports stay as they were)

DETECTOR_ROW = "LLM05: Improper Output Handling"


def item(kind: str, owasp_category: str, *, turn: int = 1, detail: str = "d") -> EvidenceItem:
    location = {"canary_in_reply": "reply", "instruction_override": "reply",
                "unsafe_executable_output": "reply"}[kind]
    return EvidenceItem(kind=kind, turn=turn, location=location, owasp_category=owasp_category, detail=detail)


def a_report_with_items(runs, evidence_by_run):
    return build_report(target=Target(), runs=runs, turns_by_run={}, recommendations={}, now=NOW,
                        evidence_by_run=evidence_by_run)


def test_the_table_has_four_tested_rows_including_the_detectors_own():  # 013/FR-045, 013/SC-008
    run_one = run(id=1, verdict="failed", reply_text="an ordinary reply")
    rows = {r.owasp_class: r for r in a_report_with_items([run_one], {}).coverage}
    assert set(rows) == TESTED | {DETECTOR_ROW}
    assert rows[DETECTOR_ROW].families == "unsafe executable output detector (every reply)"
    assert rows[DETECTOR_ROW].run_count == 1          # every run that received a reply was scanned
    assert rows[DETECTOR_ROW].result == "1 run(s), held"


def test_the_detector_row_counts_runs_that_received_a_reply_and_those_with_an_item():  # 013/FR-045
    scanned = run(id=1, verdict="succeeded", hard_evidence=True, reply_text="a reply")
    unsent = run(id=2, verdict=None, failure_step="unreachable", reply_text=None)
    rows = {r.owasp_class: r for r in a_report_with_items(
        [scanned, unsent],
        {1: [item("unsafe_executable_output", DETECTOR_ROW)]}).coverage}
    assert rows[DETECTOR_ROW].run_count == 1                      # the failed send was never scanned
    assert "1 confirmed" in rows[DETECTOR_ROW].result


def test_untested_lists_exactly_the_six_remaining_classes():  # 013/FR-045, 013/SC-008
    classes = [u.owasp_class for u in a_report([run(id=1, verdict="failed")]).untested]
    assert len(classes) == 6
    assert not any(c.startswith("LLM05") for c in classes)        # the detector covers it now
    for number in ("LLM02", "LLM03", "LLM04", "LLM08", "LLM09", "LLM10"):
        assert any(c.startswith(number) for c in classes)


def test_a_cross_class_item_never_confirms_the_familys_own_class():  # 013/FR-045
    """A system-prompt-leak run whose only item is unsafe output is not a confirmed LLM07 finding; it is
    confirmed under LLM05 alone, and still listed under LLM07 as a run - *held* there, not suspected, because the
    detector decided its turn and the judge was never asked."""
    leak = run(id=1, family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
               verdict="succeeded", hard_evidence=True, judge_used=False, reply_text="a reply")
    rows = {r.owasp_class: r for r in a_report_with_items(
        [leak], {1: [item("unsafe_executable_output", DETECTOR_ROW)]}).coverage}
    assert rows["LLM07: System Prompt Leakage"].run_count == 1
    assert rows["LLM07: System Prompt Leakage"].result == "1 run(s), held"
    assert "1 confirmed" in rows[DETECTOR_ROW].result


def test_a_judged_success_is_suspected_and_a_held_run_stays_held_beside_it():  # 013/FR-045
    judged = run(id=1, family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                 verdict="succeeded", hard_evidence=False, judge_used=True, reason="the judge thought so")
    held = run(id=2, family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
               verdict="succeeded", hard_evidence=True, judge_used=False, reply_text="a reply")
    rows = {r.owasp_class: r for r in a_report_with_items(
        [judged, held], {2: [item("unsafe_executable_output", DETECTOR_ROW)]}).coverage}
    assert rows["LLM07: System Prompt Leakage"].result == "2 run(s), 1 suspected finding(s)"


def test_a_canary_item_still_confirms_its_own_familys_class():  # 013/FR-045, 013/FR-005
    leak = run(id=1, verdict="succeeded", hard_evidence=True, reply_text="KESTREL-CANARY-9Z")
    rows = {r.owasp_class: r for r in a_report_with_items(
        [leak], {1: [item("canary_in_reply", "LLM07: System Prompt Leakage")]}).coverage}
    assert "1 confirmed" in rows["LLM07: System Prompt Leakage"].result


def test_a_pre_013_hard_evidence_run_is_still_confirmed_under_its_family():  # 013/FR-005
    leak = run(id=1, verdict="succeeded", hard_evidence=True, reply_text="KESTREL-CANARY-9Z")
    rows = {r.owasp_class: r for r in a_report_with_items([leak], {}).coverage}   # no stored items at all
    assert "1 confirmed" in rows["LLM07: System Prompt Leakage"].result
