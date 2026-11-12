"""The no-silent-change guard: the lock is clean today, and a text change without a version bump is caught and
names the prompt (009/FR-005, 009/FR-006, 009/SC-002)."""
from kestrel import prompt_registry as pr

FEATURE = "009"


def test_lock_is_clean_for_the_shipped_prompts():  # 009/FR-006, 009/SC-002
    assert pr.verify_lock() == []


def test_editing_a_prompt_without_a_bump_is_caught(monkeypatch):  # 009/FR-006, 009/SC-002
    original = pr._authored_texts()
    changed = dict(original)
    changed["judge"] = original["judge"] + " (edited without a version bump)"
    monkeypatch.setattr(pr, "_authored_texts", lambda: changed)
    assert pr.verify_lock() == ["judge"]


def test_a_prompt_missing_from_the_lock_is_caught(monkeypatch):  # 009/FR-006
    extra = dict(pr._authored_texts())
    extra["attacker:new_family"] = "a brand new attacker prompt with no lock entry"
    monkeypatch.setattr(pr, "_authored_texts", lambda: extra)
    assert "attacker:new_family" in pr.verify_lock()


def test_a_text_not_matching_its_pinned_fingerprint_is_rejected(monkeypatch):  # 009/FR-005
    # One id at one version is exactly one text: a text whose fingerprint differs from the pinned one is drift.
    changed = dict(pr._authored_texts())
    changed["recommender"] = "different text under the same recorded version"
    monkeypatch.setattr(pr, "_authored_texts", lambda: changed)
    drifted = pr.verify_lock()
    assert "recommender" in drifted and "judge" not in drifted
