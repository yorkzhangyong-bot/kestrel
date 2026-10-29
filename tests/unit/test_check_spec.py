"""check_spec.py: spec-mode requirement validation — well-formed, unique, no orphan references (feature 006).

Traces 006/FR-003, 006/FR-014, 006/SC-002, 006/SC-006. (No FEATURE marker — the bare ids below are *sample data*
for the checker, not references to 006's own requirements.) Identifiers inside inline code / fenced blocks are
ignored, so illustrative bad ids like ``FR-7``/``SC-099`` never count.
"""
from pathlib import Path

import check_spec

CLEAN = ("- **FR-001**: the system does a thing\n"
         "- **FR-002**: the system does another thing\n"
         "- **SC-001**: a measurable outcome\n\n"
         "The body mentions FR-001, FR-002 and SC-001 in prose.\n")


def feature(tmp_path: Path, spec_body: str, **extra: str) -> Path:
    directory = tmp_path / "006-sample"
    directory.mkdir()
    (directory / "spec.md").write_text(spec_body, encoding="utf-8")
    for name, text in extra.items():
        (directory / f"{name}.md").write_text(text, encoding="utf-8")
    return directory


def test_a_clean_spec_passes(tmp_path):
    assert check_spec.check(feature(tmp_path, CLEAN)) == []


def test_a_numbering_gap_is_allowed(tmp_path):
    body = "- **FR-001**: a\n- **FR-005**: b\n\nFR-001 and FR-005.\n"
    assert check_spec.check(feature(tmp_path, body)) == []


def test_a_duplicate_definition_fails(tmp_path):
    problems = check_spec.check(feature(tmp_path, CLEAN + "- **FR-001**: defined again\n"))
    assert any("FR-001" in p and "duplicate" in p for p in problems)


def test_an_orphan_reference_fails(tmp_path):
    problems = check_spec.check(feature(tmp_path, CLEAN + "\nThis refers to FR-404, which is undefined.\n"))
    assert any("FR-404" in p and "orphan" in p for p in problems)


def test_a_malformed_identifier_fails(tmp_path):
    problems = check_spec.check(feature(tmp_path, "- **FR-1**: bad\n\nSee FR-1.\n"))
    assert any("FR-1" in p and "malformed" in p for p in problems)


def test_an_orphan_reference_in_another_file_is_caught(tmp_path):
    # References are scanned across the whole feature directory, not just spec.md (clarified scope).
    problems = check_spec.check(feature(tmp_path, CLEAN, tasks="Work on FR-001 and the undefined SC-777.\n"))
    assert any("SC-777" in p and "orphan" in p for p in problems)


def test_ids_inside_inline_code_and_fenced_blocks_are_ignored(tmp_path):
    body = (CLEAN + "\nAn example of a bad id is `FR-7` or `SC-099`, which the checker rejects.\n\n"
            "```text\nmalformed identifier: FR-0001\norphan reference: SC-404\n```\n")
    assert check_spec.check(feature(tmp_path, body)) == []
