#!/usr/bin/env python3
"""Spec-mode requirement check (feature 006, FR-003, FR-014).

Runs on spec-only pull requests. Validates a feature's ``FR-###``/``SC-###`` identifiers across the feature
directory (``spec.md``, ``plan.md``, ``tasks.md``, ``contracts/`` …): each identifier is well-formed (the prefix
followed by a zero-padded three-digit number), each is defined at most once, and every referenced identifier is
defined somewhere (no orphan references). Numbering gaps are allowed.

Identifiers inside inline code spans and fenced code blocks are ignored, so illustrative examples in the docs
(e.g. ``FR-7``, ``SC-099``) are not treated as malformed ids or orphan references.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEF_RE = re.compile(r"^- \*\*((?:FR|SC)-\d+)\*\*", re.MULTILINE)
TOKEN_RE = re.compile(r"\b(?:FR|SC)-\d+\b")
WELL_FORMED_RE = re.compile(r"^(?:FR|SC)-\d{3}$")
_FENCED = re.compile(r"```.*?```", re.DOTALL)
_INLINE = re.compile(r"`[^`]*`")


def _strip_code(text: str) -> str:
    """Drop fenced code blocks then inline code spans, so ids used as examples there are not counted."""
    return _INLINE.sub(" ", _FENCED.sub(" ", text))


def _scan(feature_dir: Path) -> tuple[dict[str, int], set[str]]:
    definitions: dict[str, int] = {}
    references: set[str] = set()
    for md in sorted(feature_dir.rglob("*.md")):
        prose = _strip_code(md.read_text(encoding="utf-8"))
        for match in DEF_RE.finditer(prose):
            definitions[match.group(1)] = definitions.get(match.group(1), 0) + 1
        references.update(TOKEN_RE.findall(prose))
    return definitions, references


def check(feature_dir: Path) -> list[str]:
    """Return a list of problems ([] means valid) for a feature directory's requirement identifiers."""
    definitions, references = _scan(feature_dir)
    problems: list[str] = []
    for identifier in sorted(set(definitions) | references):
        if not WELL_FORMED_RE.match(identifier):
            problems.append(f"malformed identifier: {identifier} (expected FR-### / SC-### with three digits)")
    for identifier, count in sorted(definitions.items()):
        if count > 1:
            problems.append(f"duplicate definition: {identifier} is defined {count} times")
    for identifier in sorted(references):
        if WELL_FORMED_RE.match(identifier) and identifier not in definitions:
            problems.append(f"orphan reference: {identifier} is referenced but never defined")
    return problems


def _branch_name() -> str:
    ref = os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME")
    if ref:
        return ref
    done = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return done.stdout.strip()


def _resolve_feature_dir(argv: list[str]) -> Path | None:
    if len(argv) > 1:
        path = Path(argv[1])
        return path if path.is_absolute() else ROOT / path
    match = re.match(r"(\d{3,})", _branch_name())
    if not match:
        return None
    matches = sorted(ROOT.glob(f"specs/{match.group(1)}-*"))
    return matches[0] if matches else None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    feature_dir = _resolve_feature_dir(argv)
    if feature_dir is None:
        print("No feature directory given and no numeric branch prefix; nothing to check.")
        return 0
    if not feature_dir.exists():
        print(f"Feature directory not found: {feature_dir}")
        return 1

    problems = check(feature_dir)
    rel = feature_dir.relative_to(ROOT).as_posix() if feature_dir.is_relative_to(ROOT) else str(feature_dir)
    if problems:
        print(f"Spec check failed for {rel}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    definitions, _ = _scan(feature_dir)
    fr = sum(1 for identifier in definitions if identifier.startswith("FR"))
    sc = sum(1 for identifier in definitions if identifier.startswith("SC"))
    print(f"{rel}: {fr} FR, {sc} SC defined; all well-formed, unique, no orphan references.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
