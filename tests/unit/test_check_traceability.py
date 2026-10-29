"""check_traceability.py PR-rule helpers for implementation PRs (feature 006).

Traces 006/FR-002 (classification), 006/FR-009 (Spec-PR reference), 006/FR-010, 006/FR-011 (spec-change note),
006/SC-003, 006/SC-007. (No FEATURE marker — the bare ids in the samples below are not references to 006's own
requirements.) These pure helpers take plain arguments so the rules are tested without GitHub.
"""
import check_traceability as ct


def test_is_spec_only_depends_only_on_code_dirs():
    assert ct.is_spec_only(["specs/006-x/spec.md", "docs/qa-pipeline.md"]) is True
    assert ct.is_spec_only([".github/workflows/qa.yml", "specs/006-x/plan.md"]) is True   # non-code config is ok
    assert ct.is_spec_only(["specs/006-x/spec.md", "src/kestrel/store.py"]) is False
    assert ct.is_spec_only(["tests/unit/test_x.py"]) is False
    assert ct.is_spec_only(["scripts/check_spec.py"]) is False


def test_spec_change_note_required_only_with_a_spec_and_src_change():
    both = ["specs/006-x/spec.md", "src/kestrel/store.py"]
    assert ct.needs_spec_change_note(both) is True
    assert ct.spec_change_ok(both, "just a description") is False
    assert ct.spec_change_ok(both, "spec-change: narrowed FR-003\n") is True
    # Not required when src is untouched, or when no spec file changed.
    assert ct.needs_spec_change_note(["specs/006-x/spec.md", "scripts/check_spec.py"]) is False
    assert ct.spec_change_ok(["src/kestrel/store.py"], "") is True


def test_has_spec_pr_reference():
    assert ct.has_spec_pr_reference("Implements the thing.\nSpec-PR: #2\n") is True
    assert ct.has_spec_pr_reference("Spec-PR:#12") is True
    assert ct.has_spec_pr_reference("no reference at all") is False
    assert ct.has_spec_pr_reference("") is False
    assert ct.has_spec_pr_reference(None) is False


def test_justified_identifiers_parses_feature_scoped_lines():
    # A requirement counts as traced when justified as a feature-scoped line "<prefix>/FR-00x: <reason>".
    # Sample ids are outside the 006 range so this test does not itself trace real requirements.
    text = ("# Traceability\n\n"
            "- 006/FR-900: justified outside unit tests\n"
            "- 006-SC-901: enforced by branch protection\n"
            "006/FR-902: manual settings in a doc\n"
            "007/FR-903: belongs to another feature\n"
            "FR-904: no feature prefix, not counted\n")
    assert ct.justified_identifiers(text, "006") == {"FR-900", "SC-901", "FR-902"}
