"""The one-line situation summary: built from judge progress notes, no model call, sanitised (FR-008, FR-013)."""
from kestrel.experience.summary import MAX_SUMMARY_CHARS, build_summary

FEATURE = "004"


def test_summary_joins_judge_progress_notes():
    s = build_summary(["got a refusal", "agent wavered", "still held"],
                      family="system_prompt_leak", verdict="failed", hard_evidence=False,
                      turns_used=3, stopping_condition="turn_cap")
    assert "got a refusal" in s and "still held" in s
    assert "\n" not in s and len(s) <= MAX_SUMMARY_CHARS


def test_summary_falls_back_to_metadata_when_no_notes():
    s = build_summary([], family="direct_injection", verdict="succeeded", hard_evidence=True,
                      turns_used=1, stopping_condition="succeeded")
    assert "direct_injection" in s and "succeeded" in s
    assert "canary" in s.lower()  # hard evidence is noted in the fallback


def test_summary_ignores_empty_notes_and_uses_fallback():
    s = build_summary([None, "", "   "], family="tool_exfiltration", verdict="unclear", hard_evidence=False,
                      turns_used=2, stopping_condition="time_limit")
    assert "tool_exfiltration" in s and "unclear" in s


def test_summary_is_sanitised_to_one_bounded_line():
    noisy = "line one\nline two\twith\ttabs\x07bell " + ("x" * 500)
    s = build_summary([noisy], family="direct_injection", verdict="failed", hard_evidence=False,
                      turns_used=1, stopping_condition="turn_cap")
    assert "\n" not in s and "\t" not in s and "\x07" not in s
    assert len(s) <= MAX_SUMMARY_CHARS


def test_summary_truncates_at_a_word_boundary():
    long = " ".join(f"token{i:03d}" for i in range(80))  # ~640 chars of whole words
    s = build_summary([long], family="direct_injection", verdict="failed", hard_evidence=False,
                      turns_used=2, stopping_condition="turn_cap")
    assert len(s) <= MAX_SUMMARY_CHARS and s.endswith("…")
    body = s[:-1]
    assert long.startswith(body) and long[len(body)] == " "  # cut on a whole word, not mid-word


def test_fallback_omits_the_stopping_clause_when_there_is_none():
    s = build_summary([], family="system_prompt_leak", verdict="failed", hard_evidence=False,
                      turns_used=1, stopping_condition=None)
    assert "n/a" not in s and "stopped at" not in s
    assert "system_prompt_leak" in s and "failed" in s


def test_fallback_keeps_the_stopping_clause_when_present():
    s = build_summary([], family="direct_injection", verdict="unclear", hard_evidence=False,
                      turns_used=2, stopping_condition="time_limit")
    assert "stopped at time_limit" in s
