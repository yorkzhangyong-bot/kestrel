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
    assert set(rows) == TESTED                                             # exactly the three in-scope classes
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


def test_untested_lists_exactly_the_seven_other_classes_each_with_a_reason():
    classes = [u.owasp_class for u in a_report([run(id=1, verdict="failed")]).untested]
    assert len(classes) == 7
    for number in ("LLM02", "LLM03", "LLM04", "LLM05", "LLM08", "LLM09", "LLM10"):
        assert any(c.startswith(number) for c in classes)
    assert all(u.reason.strip() for u in a_report([run(id=1, verdict="failed")]).untested)
