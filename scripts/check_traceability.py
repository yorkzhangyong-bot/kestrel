#!/usr/bin/env python3
"""Traceability gate: every requirement id in the feature's spec must be referenced by at least one test.

The feature is taken from the branch-name prefix (``005-owasp-report`` -> feature ``005``); the spec is
``specs/<nnn>-*/spec.md``. Every ``FR-nnn`` and ``SC-nnn`` identifier in that spec must appear somewhere under
``tests/`` (matched as a whole token, so ``FR-1`` does not satisfy ``FR-10``). Unreferenced identifiers are
printed and the script exits 1. A branch with no numeric feature prefix has nothing to trace and exits 0.
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


def main() -> int:
    branch = branch_name()
    prefix = feature_prefix(branch)
    if prefix is None:
        print(f"No numeric feature prefix in branch {branch!r}; nothing to trace.")
        return 0

    spec = find_spec(prefix)
    if spec is None:
        print(f"No spec found for feature {prefix} (expected specs/{prefix}-*/spec.md).")
        return 1

    ids = spec_identifiers(spec)
    rel = spec.relative_to(ROOT).as_posix()
    if not ids:
        print(f"No FR-/SC- identifiers found in {rel}; nothing to trace.")
        return 0

    referenced = identifiers_referenced_by_tests()
    unreferenced = [identifier for identifier in ids if identifier not in referenced]

    print(f"Feature {prefix}: {len(ids)} requirement id(s) in {rel}; "
          f"{len(ids) - len(unreferenced)} referenced under tests/.")
    if unreferenced:
        print("Unreferenced identifiers (no test mentions them):")
        for identifier in unreferenced:
            print(f"  - {identifier}")
        return 1

    print("All requirement identifiers are referenced by at least one test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
