"""scripts/bump_prompt.py: copy the active prompt file to the next version, then record its fingerprint in the lock —
the bump flow behind the guard (009/FR-005, 009/FR-006, 009/SC-002). Runs on a copy of the shipped files."""
import shutil

import pytest

import bump_prompt
from kestrel import prompt_registry as pr

FEATURE = "009"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    shutil.copytree(pr.PROMPTS_DIR, prompts)
    lock = tmp_path / "prompt_versions.lock.json"
    shutil.copy(pr.LOCK_PATH, lock)
    monkeypatch.setattr(pr, "PROMPTS_DIR", prompts)
    monkeypatch.setattr(pr, "LOCK_PATH", lock)
    return prompts, lock


def test_bump_copies_the_active_file_to_the_next_version(sandbox):  # 009/SC-002
    prompts, lock = sandbox
    created = bump_prompt.bump("judge", directory=prompts, lock_path=lock)
    assert created == prompts / "judge.v2.md" and created.is_file()
    parsed = pr.parse_prompt_file(created)
    assert (parsed.id, parsed.version) == ("judge", "2")
    assert parsed.text == pr.text_for("judge", "1")          # the same text, ready to edit
    assert pr.active_version("judge") == "2"                  # the new file is the active version now...
    assert pr.verify_lock() == ["judge"]                      # ...and the guard is red until it is recorded


def test_lock_records_the_edited_text_and_turns_the_guard_green(sandbox):  # 009/FR-006, 009/SC-002
    prompts, lock = sandbox
    created = bump_prompt.bump("judge", directory=prompts, lock_path=lock)
    created.write_text(pr.format_prompt_file("judge", "2", "a sharper judge prompt"), encoding="utf-8", newline="\n")
    message = bump_prompt.record("judge", directory=prompts, lock_path=lock)
    assert "judge@2" in message
    assert pr.read_lock(lock)["judge"]["2"] == pr.fingerprint("a sharper judge prompt")
    assert pr.verify_lock() == []
    assert pr.load_prompt("judge") == ("a sharper judge prompt", "judge@2")


def test_bump_refuses_to_stack_an_unrecorded_version(sandbox):  # 009/FR-005
    prompts, lock = sandbox
    bump_prompt.bump("judge", directory=prompts, lock_path=lock)
    with pytest.raises(bump_prompt.BumpError, match="not recorded"):
        bump_prompt.bump("judge", directory=prompts, lock_path=lock)


def test_lock_refuses_to_rewrite_a_recorded_version_unless_forced(sandbox):  # 009/FR-005
    prompts, lock = sandbox
    pr.prompt_path("judge", "1", prompts).write_text(pr.format_prompt_file("judge", "1", "silently changed"),
                                                    encoding="utf-8", newline="\n")
    with pytest.raises(bump_prompt.BumpError, match="already recorded"):
        bump_prompt.record("judge", directory=prompts, lock_path=lock)
    assert pr.verify_lock() == ["judge"]                      # still red: the lock was not touched
    bump_prompt.record("judge", directory=prompts, lock_path=lock, force=True)
    assert pr.verify_lock() == []


def test_lock_is_a_no_op_when_already_recorded(sandbox):  # 009/FR-005
    prompts, lock = sandbox
    before = lock.read_text(encoding="utf-8")
    assert "already recorded" in bump_prompt.record("judge", directory=prompts, lock_path=lock)
    assert lock.read_text(encoding="utf-8") == before


def test_lock_registers_a_brand_new_prompt_id(sandbox):  # 009/FR-006
    prompts, lock = sandbox
    pr.prompt_path("attacker:new_family", "1", prompts).write_text(
        pr.format_prompt_file("attacker:new_family", "1", "a new family's attacker prompt"), encoding="utf-8",
        newline="\n")
    assert "attacker:new_family" in pr.verify_lock()
    bump_prompt.record("attacker:new_family", directory=prompts, lock_path=lock)
    assert pr.verify_lock() == []


def test_an_unknown_id_is_an_error(sandbox):  # 009/FR-009
    prompts, lock = sandbox
    with pytest.raises(bump_prompt.BumpError, match="No prompt"):
        bump_prompt.bump("attacker:nope", directory=prompts, lock_path=lock)


def test_main_exit_codes(sandbox, capsys):  # 009/SC-002
    assert bump_prompt.main(["judge"]) == 0
    assert "judge.v2.md" in capsys.readouterr().out
    assert bump_prompt.main(["judge"]) == 2                   # v2 is not recorded yet: refuse to stack a v3
    assert bump_prompt.main(["judge", "--lock"]) == 0
    assert "Guard: clean" in capsys.readouterr().out
    assert bump_prompt.main(["nope"]) == 2
