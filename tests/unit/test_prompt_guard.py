"""The no-silent-change guard over the prompt files: the lock is clean today, and a text change without a version
bump — or a version file the lock does not pin, or a pinned version with no file — is caught and names the prompt
(009/FR-005, 009/FR-006, 009/SC-002). The edits happen on a copy of the shipped files, never the repo's."""
import shutil

import pytest

from kestrel import prompt_registry as pr

FEATURE = "009"


def test_lock_is_clean_for_the_shipped_prompts():  # 009/FR-006, 009/SC-002
    assert pr.verify_lock() == []


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A copy of the shipped prompt files and lock, pointed at by the registry for the test's duration."""
    prompts = tmp_path / "prompts"
    shutil.copytree(pr.PROMPTS_DIR, prompts)
    lock = tmp_path / "prompt_versions.lock.json"
    shutil.copy(pr.LOCK_PATH, lock)
    monkeypatch.setattr(pr, "PROMPTS_DIR", prompts)
    monkeypatch.setattr(pr, "LOCK_PATH", lock)
    assert pr.verify_lock() == []   # the copy starts clean
    return prompts


def _rewrite(prompts, prompt_id, version, text):
    path = pr.prompt_path(prompt_id, version, prompts)
    path.write_text(pr.format_prompt_file(prompt_id, version, text), encoding="utf-8", newline="\n")
    return path


def test_editing_a_prompt_file_without_a_bump_is_caught(sandbox):  # 009/FR-006, 009/SC-002
    _rewrite(sandbox, "judge", "1", pr.text_for("judge", "1") + " (edited without a version bump)")
    assert pr.verify_lock() == ["judge"]


def test_bumping_the_version_and_recording_the_fingerprint_makes_it_pass(sandbox):  # 009/SC-002
    _rewrite(sandbox, "judge", "2", "a sharper judge prompt")
    assert pr.verify_lock() == ["judge"]           # a new version file the lock does not pin yet
    lock = pr.read_lock()
    lock["judge"]["2"] = pr.fingerprint("a sharper judge prompt")
    pr.write_lock(lock)
    assert pr.verify_lock() == []
    assert pr.active_version("judge") == "2"
    assert pr.text_for("judge", "1")               # the older file stays as the non-active version


def test_a_prompt_file_missing_from_the_lock_is_caught(sandbox):  # 009/FR-006
    _rewrite(sandbox, "attacker:new_family", "1", "a brand new attacker prompt with no lock entry")
    assert "attacker:new_family" in pr.verify_lock()


def test_a_pinned_version_with_no_file_is_caught(sandbox):  # 009/FR-006
    pr.prompt_path("recommender", "1", sandbox).unlink()
    assert pr.verify_lock() == ["recommender"]


def test_a_text_not_matching_its_pinned_fingerprint_is_rejected(sandbox):  # 009/FR-005
    # One id at one version is exactly one text: a text whose fingerprint differs from the pinned one is drift.
    _rewrite(sandbox, "recommender", "1", "different text under the same recorded version")
    drifted = pr.verify_lock()
    assert "recommender" in drifted and "judge" not in drifted


def test_a_malformed_prompt_file_is_named_by_the_guard_and_loud_in_lookups(sandbox):  # 009/FR-006
    (sandbox / "judge.v2.md").write_text("---\nid: judge\nversion: 1\n---\ntext\n", encoding="utf-8", newline="\n")
    assert "judge.v2.md" in pr.verify_lock()
    with pytest.raises(pr.PromptFileError):
        pr.load_prompt("judge")


def test_a_lock_version_outside_the_integer_scheme_is_caught(sandbox):  # 009/FR-005
    lock = pr.read_lock()
    lock["judge"]["1.0.0"] = lock["judge"]["1"]
    pr.write_lock(lock)
    assert pr.verify_lock() == ["judge"]
