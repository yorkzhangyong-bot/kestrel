#!/usr/bin/env python3
"""Traceability gate for implementation pull requests (feature 005, extended by feature 006).

Two things, both on implementation PRs (the workflow runs ``check_spec.py`` instead on spec-only PRs):

1. **Tests-traceability** — every ``FR-nnn``/``SC-nnn`` in the feature's ``specs/<nnn>-*/spec.md`` must either
   appear somewhere under ``tests/`` (matched as a whole token, so ``FR-1`` does not satisfy ``FR-10``) **or** be
   justified in ``specs/<nnn>-*/traceability.md`` as a line ``FR-00x: <justification>`` — for requirements that are
   enforced outside unit tests (branch protection, CODEOWNERS, docs) and verified manually.
2. **Implementation-PR rules** (feature 006) — the PR description must carry a ``Spec-PR: #<n>`` reference
   (FR-009), and a PR that edits a spec file alongside a ``src/`` change must carry a ``spec-change:`` note
   (FR-010/FR-011).

Unreferenced ids or a broken rule are printed and the script exits 1. A branch with no numeric feature prefix
skips tests-traceability; a PR with no code-directory change is not an implementation PR and skips the rules.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
ID_RE = re.compile(r"\b(?:FR|SC)-\d+\b")
# A justification line in specs/<nnn>-*/traceability.md: "FR-00x: <justification>" (optionally bulleted).
JUSTIFIED_RE = re.compile(r"(?m)^\s*-?\s*((?:FR|SC)-\d+):\s*\S")
CODE_DIRS = ("src/", "tests/", "ui/", "scripts/")
SPEC_CHANGE_RE = re.compile(r"(?im)^spec-change:\s*\S")
SPEC_PR_RE = re.compile(r"(?im)^Spec-PR:\s*#\d+")


def branch_name() -> str:
    """The PR source branch in CI (GITHUB_HEAD_REF), else the current git branch."""
    ref = os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME")
    if ref:
        return ref
    try:
        done = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                              cwd=ROOT, capture_output=True, text=True, check=True)
        return done.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def feature_prefix(branch: str) -> str | None:
    match = re.match(r"(\d{3,})", branch)
    return match.group(1) if match else None


def find_spec(prefix: str) -> Path | None:
    matches = sorted(ROOT.glob(f"specs/{prefix}-*/spec.md"))
    return matches[0] if matches else None


def _sort_key(identifier: str) -> tuple[str, int]:
    kind, number = identifier.split("-")
    return kind, int(number)


def spec_identifiers(spec: Path) -> list[str]:
    return sorted(set(ID_RE.findall(spec.read_text(encoding="utf-8"))), key=_sort_key)


def identifiers_referenced_by_tests() -> set[str]:
    referenced: set[str] = set()
    for path in sorted(TESTS_DIR.rglob("*.py")):
        referenced.update(ID_RE.findall(path.read_text(encoding="utf-8", errors="replace")))
    return referenced


def justified_identifiers(text: str) -> set[str]:
    """Requirement ids justified in a traceability.md body, as lines ``FR-00x: <justification>``."""
    return set(JUSTIFIED_RE.findall(text))


def find_traceability(prefix: str) -> Path | None:
    matches = sorted(ROOT.glob(f"specs/{prefix}-*/traceability.md"))
    return matches[0] if matches else None


def identifiers_justified(prefix: str) -> set[str]:
    """Ids a feature justifies outside tests, from specs/<prefix>-*/traceability.md (empty if the file is absent)."""
    path = find_traceability(prefix)
    return justified_identifiers(path.read_text(encoding="utf-8")) if path else set()


# ---- implementation-PR rules (feature 006) ----

def changed_files() -> list[str]:
    """The PR's changed paths via git diff against the base ref. Empty when not in a PR context."""
    base = os.environ.get("GITHUB_BASE_REF")
    if not base:
        return []
    subprocess.run(["git", "fetch", "--quiet", "origin", base], cwd=ROOT, capture_output=True, text=True)
    done = subprocess.run(["git", "diff", "--name-only", f"origin/{base}...HEAD"],
                          cwd=ROOT, capture_output=True, text=True)
    return [line.strip() for line in done.stdout.splitlines() if line.strip()]


def is_spec_only(files: list[str]) -> bool:
    """True when the PR changes nothing under src/, tests/, ui/, or scripts/ (FR-002)."""
    return not any(path.startswith(CODE_DIRS) for path in files)


def needs_spec_change_note(files: list[str]) -> bool:
    """True when the PR edits a spec file in the same change as a src/ file (FR-010)."""
    return any(p.startswith("specs/") for p in files) and any(p.startswith("src/") for p in files)


def spec_change_ok(files: list[str], pr_body: str | None) -> bool:
    return not needs_spec_change_note(files) or bool(SPEC_CHANGE_RE.search(pr_body or ""))


def has_spec_pr_reference(pr_body: str | None) -> bool:
    """True when the description carries a ``Spec-PR: #<n>`` line (FR-009)."""
    return bool(SPEC_PR_RE.search(pr_body or ""))


def _pr_rule_problems() -> list[str]:
    files = changed_files()
    if not files or is_spec_only(files):
        return []   # not an implementation PR (or no PR context)
    pr_body = os.environ.get("PR_BODY", "")
    problems: list[str] = []
    if not has_spec_pr_reference(pr_body):
        problems.append("implementation PR description lacks a 'Spec-PR: #<n>' reference line (FR-009)")
    if not spec_change_ok(files, pr_body):
        problems.append("a spec file changed alongside a src/ change without a 'spec-change:' note (FR-010/FR-011)")
    return problems


def _traceability_problems() -> list[str]:
    prefix = feature_prefix(branch_name())
    if prefix is None:
        print("No numeric feature prefix; skipping tests-traceability.")
        return []
    spec = find_spec(prefix)
    if spec is None:
        return [f"no spec found for feature {prefix} (expected specs/{prefix}-*/spec.md)"]
    ids = spec_identifiers(spec)
    rel = spec.relative_to(ROOT).as_posix()
    if not ids:
        print(f"No FR-/SC- identifiers found in {rel}; nothing to trace.")
        return []
    traced = identifiers_referenced_by_tests() | identifiers_justified(prefix)
    untraced = [identifier for identifier in ids if identifier not in traced]
    print(f"Feature {prefix}: {len(ids)} requirement id(s) in {rel}; "
          f"{len(ids) - len(untraced)} traced (referenced by a test or justified in traceability.md).")
    return [f"requirement {identifier} is neither referenced by a test nor justified in "
            f"specs/{prefix}-*/traceability.md" for identifier in untraced]


def main() -> int:
    problems = _pr_rule_problems() + _traceability_problems()
    if problems:
        print("Traceability check failed:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("Traceability OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
