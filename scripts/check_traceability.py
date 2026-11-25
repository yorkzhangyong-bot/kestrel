#!/usr/bin/env python3
"""Traceability gate for implementation pull requests (feature 005, feature-scoped and extended by feature 006).

Two things, both on implementation PRs (the workflow runs ``check_spec.py`` instead on spec-only PRs):

1. **Feature-scoped tests-traceability** — every ``FR-nnn``/``SC-nnn`` in the feature's ``specs/<nnn>-*/spec.md``
   must either (a) be referenced by a test **that names the feature** — a scoped token ``<nnn>/FR-001`` or
   ``<nnn>-FR-001`` anywhere, or a bare ``FR-001`` in a file carrying a module-level ``FEATURE = "<nnn>"`` marker —
   or (b) be justified in ``specs/<nnn>-*/traceability.md`` as a line ``<nnn>/FR-00x: <justification>``. Scoping
   stops one feature's tests from accidentally "covering" another feature's same-numbered id.
2. **Implementation-PR rules** (feature 006) — a PR that changes ``src/`` or ``ui/`` (on **any** branch) must
   declare its spec provenance: ``Spec-PR: #<n>``, referencing the merged spec PR, or ``Spec-PR: none`` together
   with exactly one reason line (``Spec-PR-reason: refactor`` or ``Spec-PR-reason: bugfix: #<issue>``) and the
   matching pull-request label (the honest path, FR-015–FR-024); a PR that edits a spec file alongside a ``src/``
   change must also carry a ``spec-change:`` note (FR-010/FR-011). The description and the labels are read live
   from the platform at evaluation time (``gh pr view``, FR-018); a ``bugfix: #<issue>`` reason is accepted only
   once a live lookup finds the number as an issue of this repository (FR-024, ``gh api``).

Untraced ids or a broken rule are printed and the script exits 1. A branch with no numeric feature prefix skips
tests-traceability (that part stays feature-scoped); the Spec-PR rule, though, fires for any PR that changes
``src/`` or ``ui/`` whatever the branch is named.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
ID_RE = re.compile(r"\b(?:FR|SC)-\d+\b")
CODE_DIRS = ("src/", "tests/", "ui/", "scripts/")
APP_DIRS = ("src/", "ui/")   # application code: a change here needs a Spec-PR reference (FR-009), on any branch
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


# ---- feature-scoped traceability (feature 006) ----

def _scoped_token_re(prefix: str) -> re.Pattern[str]:
    """A feature-scoped id reference, e.g. ``006/FR-001`` or ``006-FR-001``; captures the bare id."""
    return re.compile(rf"\b{re.escape(prefix)}[-/]((?:FR|SC)-\d+)\b")


def _feature_marker_re(prefix: str) -> re.Pattern[str]:
    """A module-level marker line: ``FEATURE = "006"``."""
    return re.compile(rf'(?m)^\s*FEATURE\s*=\s*["\']{re.escape(prefix)}["\']')


def identifiers_traced_by_tests(prefix: str) -> set[str]:
    """Ids a test references *for feature <prefix>*: a scoped token anywhere, or a bare id in a file that carries
    a module-level ``FEATURE = "<prefix>"`` marker."""
    scoped = _scoped_token_re(prefix)
    marker = _feature_marker_re(prefix)
    traced: set[str] = set()
    for path in sorted(TESTS_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        traced.update(scoped.findall(text))
        if marker.search(text):
            traced.update(ID_RE.findall(text))
    return traced


def justified_identifiers(text: str, prefix: str) -> set[str]:
    """Ids justified in a traceability.md body as feature-scoped lines ``<prefix>/FR-00x: <justification>``."""
    pattern = re.compile(rf"(?m)^\s*-?\s*{re.escape(prefix)}[-/]((?:FR|SC)-\d+):\s*\S")
    return set(pattern.findall(text))


def find_traceability(prefix: str) -> Path | None:
    matches = sorted(ROOT.glob(f"specs/{prefix}-*/traceability.md"))
    return matches[0] if matches else None


def identifiers_justified(prefix: str) -> set[str]:
    """Ids a feature justifies outside tests, from specs/<prefix>-*/traceability.md (empty if the file is absent)."""
    path = find_traceability(prefix)
    return justified_identifiers(path.read_text(encoding="utf-8"), prefix) if path else set()


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


def changes_app_code(files: list[str]) -> bool:
    """True when the PR changes application code (src/ or ui/). Such a PR MUST carry a Spec-PR reference (FR-009),
    regardless of the branch name, so bugfix and infrastructure branches (fix/*, chore/*, eval/*) meet the same
    bar as a feature branch."""
    return any(path.startswith(APP_DIRS) for path in files)


def needs_spec_change_note(files: list[str]) -> bool:
    """True when the PR edits a spec file in the same change as a src/ file (FR-010)."""
    return any(p.startswith("specs/") for p in files) and any(p.startswith("src/") for p in files)


def spec_change_ok(files: list[str], pr_body: str | None) -> bool:
    return not needs_spec_change_note(files) or bool(SPEC_CHANGE_RE.search(pr_body or ""))


def has_spec_pr_reference(pr_body: str | None) -> bool:
    """True when the description carries a ``Spec-PR: #<n>`` line (FR-009). Unchanged by the honest path."""
    return bool(SPEC_PR_RE.search(pr_body or ""))


# ---- the honest Spec-PR path for refactor and bug-fix PRs (feature 006, FR-015-FR-024) ----

SPEC_PR_LINE_RE = re.compile(r"(?im)^Spec-PR:[ \t]*(.*)$")        # every keyed Spec-PR: line, raw value captured
REASON_LINE_RE = re.compile(r"(?im)^Spec-PR-reason:[ \t]*(.*)$")  # every reason line, raw value captured
REASON_VALUE_RE = re.compile(r"(?i)^(?:(refactor)|(bugfix):[ \t]*#([0-9]+))$")   # a well-formed reason; group 3 digits
REASON_LABELS = {"refactor": "refactor", "bugfix": "bugfix"}              # reason keyword -> required PR label

_HINT = "every column-1 keyed line counts, also inside code blocks and HTML comments; indent quoted examples"
_ACCEPTED_FORMS = ("Accepted forms: 'Spec-PR: #<n>'; or 'Spec-PR: none' + 'Spec-PR-reason: refactor' + label "
                   "'refactor'; or 'Spec-PR: none' + 'Spec-PR-reason: bugfix: #<issue>' + label 'bugfix'.")


def _lit(value: str) -> str:
    """repr(), truncated to 80 chars: an echoed description value can never start a runner log line or a
    workflow command (FR-020)."""
    text = repr(value)
    return text if len(text) <= 80 else text[:77] + "..."


def spec_pr_rule_problems(pr_body: str | None, labels: list[str],
                           issue_exists: Callable[[str], bool]) -> list[str]:
    """The Spec-PR declaration rule (FR-009, FR-015-FR-018, FR-020, FR-022, FR-024): the eleven-row decision order
    of contracts/pr-rules.md, over the **raw** description (no comment or markup filter; a keyed line starts in
    column 1, FR-017). Returns at most one problem; every failure message ends with the accepted-forms sentence.
    """
    body = pr_body or ""
    numbered = bool(SPEC_PR_RE.search(body))
    # `.rstrip(...)` here, not a `[ \t\r]*$` tail in the pattern: the old `(.*?)[ \t\r]*$` (non-greedy, then an
    # optional trailing class) was quadratic on a long, space-padded line (34.3 s at 65,000 characters); the
    # greedy `(.*)$` used instead is linear (review finding 10, confirmed again at review finding 2 of round 2 -
    # measured 0.000 s at the same length).
    values = [value.rstrip(" \t\r") for value in SPEC_PR_LINE_RE.findall(body)]
    none_valued = [value for value in values if value.lower().startswith("none")]
    reasons = [reason.rstrip(" \t\r") for reason in REASON_LINE_RE.findall(body)]
    names = {name.lower() for name in labels}
    if numbered and not none_valued and not reasons:
        return []   # row 1: the numbered form, unchanged behaviour (SC-009)
    if numbered:
        return [f"conflicting declaration: 'Spec-PR: #<n>' beside a 'Spec-PR: none' or a 'Spec-PR-reason:' line "
                f"(FR-016); {_HINT}. {_ACCEPTED_FORMS}"]   # row 2
    if not none_valued:
        detail = f"; malformed Spec-PR value(s): {', '.join(_lit(v) for v in values)}" if values else ""
        return [f"a PR that changes src/ or ui/ must carry a Spec-PR declaration (FR-009){detail}. "
                f"{_ACCEPTED_FORMS}"]   # row 3
    if len(values) != 1 or values[0].lower() != "none":
        return [f"the honest path needs exactly one 'Spec-PR:' line with the value 'none'; found "
                f"{', '.join(_lit(v) for v in values)} (FR-016); {_HINT}. {_ACCEPTED_FORMS}"]   # row 4
    if not reasons:
        return [f"'Spec-PR: none' needs a 'Spec-PR-reason:' line (FR-016). {_ACCEPTED_FORMS}"]   # row 5
    if len(reasons) > 1:
        return [f"more than one 'Spec-PR-reason:' line (FR-016); {_HINT}. {_ACCEPTED_FORMS}"]   # row 6
    match = REASON_VALUE_RE.match(reasons[0])
    if not match:
        return [f"malformed reason {_lit(reasons[0])} (FR-016). {_ACCEPTED_FORMS}"]   # row 7
    keyword = "refactor" if match.group(1) else "bugfix"
    other = "bugfix" if keyword == "refactor" else "refactor"
    if REASON_LABELS[keyword] not in names:
        return [f"reason '{keyword}' needs the '{REASON_LABELS[keyword]}' label (FR-015, FR-016). "
                f"{_ACCEPTED_FORMS}"]   # row 8
    if REASON_LABELS[other] in names:
        return [f"the '{REASON_LABELS[other]}' label contradicts the reason '{keyword}' (FR-016). "
                f"{_ACCEPTED_FORMS}"]   # row 9
    if keyword == "bugfix":
        number = match.group(3)   # digits only
        if not issue_exists(number):
            return [f"'bugfix: #{number}': #{number} is not an issue of this repository (a pull request, a "
                    f"transferred or deleted issue, a number that does not exist, or a failed lookup) (FR-024). "
                    f"{_ACCEPTED_FORMS}"]   # row 10
    return []   # row 11: the honest path is satisfied


def parse_pr_state(raw: str | None) -> tuple[str, list[str]]:
    """Turn ``gh pr view --json body,labels`` output into ``(body, label names)``; any unexpected shape ->
    ``("", [])`` (FR-018)."""
    if not raw:
        return "", []
    try:
        data = json.loads(raw)
    except ValueError:
        return "", []
    if not isinstance(data, dict):
        return "", []
    body = data.get("body")
    body = body if isinstance(body, str) else ""
    labels = data.get("labels")
    if not isinstance(labels, list) or not all(
        isinstance(entry, dict) and isinstance(entry.get("name"), str) for entry in labels
    ):
        return body, []
    return body, [entry["name"] for entry in labels]


def pr_state() -> tuple[str, list[str]]:
    """The live read (FR-018): ``gh pr view`` with the job's own token, at evaluation time — never the triggering
    event's snapshot, so a manual re-run and overlapping runs all judge the same, current state. Any failure (no
    ``PR_NUMBER``, a non-zero exit, a timeout, no ``gh`` on the path, any other exception) -> ``("", [])``, so the
    honest path and the numbered form both fail closed; the notice never carries a body or label value."""
    number = os.environ.get("PR_NUMBER")
    if not number:
        print("PR state: PR_NUMBER is not set; treating the description as empty and the labels as none.")
        return "", []
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    try:
        done = subprocess.run(["gh", "pr", "view", number, "--repo", repo, "--json", "body,labels"],
                              capture_output=True, text=True, timeout=30)
    except Exception as exc:
        print(f"PR state: the live read failed ({type(exc).__name__}); treating the description as empty and "
              f"the labels as none.")
        return "", []
    if done.returncode != 0:
        print(f"PR state: gh exited {done.returncode}; treating the description as empty and the labels as none.")
        return "", []
    return parse_pr_state(done.stdout)


def parse_issue_lookup(raw: str | None, repository: str, number: str) -> bool:
    """True only for a JSON issue object of this repository (FR-024): no ``pull_request`` key (the issues
    endpoint returns pull requests too), a matching ``number``, and a ``repository_url`` ending with
    ``/repos/<repository>`` (case-insensitive, so a transfer fails whether or not the redirect was followed).
    ``state`` is ignored: open or closed both pass."""
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except ValueError:
        return False
    if not isinstance(data, dict) or "pull_request" in data:
        return False
    try:
        target = int(number)
    except ValueError:   # an absurdly long digit string (CPython's int-string conversion limit): fail closed
        return False
    if data.get("number") != target:
        return False
    url = data.get("repository_url")
    return isinstance(url, str) and url.lower().endswith("/repos/" + repository.lower())


def issue_exists_in_repo(number: str) -> bool:
    """The live issue lookup (FR-024), called only on the bugfix path once every other condition holds. Any
    failure (a non-zero ``gh`` exit, a timeout, no ``gh`` on the path, invalid JSON, any other exception) ->
    ``False``; every notice names only the digits, never a description or label value."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    try:
        done = subprocess.run(["gh", "api", f"repos/{repo}/issues/{number}"],
                              capture_output=True, text=True, timeout=30)
    except Exception as exc:
        print(f"Issue lookup for #{number} failed ({type(exc).__name__}); treating it as not an issue of this "
              f"repository.")
        return False
    if done.returncode != 0:
        print(f"Issue lookup for #{number}: gh exited {done.returncode}; treating it as not an issue of this "
              f"repository.")
        return False
    return parse_issue_lookup(done.stdout, repo, number)


def pr_rule_problems(files: list[str], pr_body: str | None, labels: list[str],
                      issue_exists: Callable[[str], bool]) -> list[str]:
    """The pure wiring (FR-009, FR-010, FR-011, FR-015-FR-024): nothing to check outside a PR context or on a
    spec-only PR; the Spec-PR declaration rule only when the PR changes ``src/`` or ``ui/``; the spec-change rule
    always, on the honest path exactly as on any other (FR-022)."""
    if not files or is_spec_only(files):
        return []   # not an implementation PR (or no PR context)
    problems = spec_pr_rule_problems(pr_body, labels, issue_exists) if changes_app_code(files) else []
    if not spec_change_ok(files, pr_body):
        problems.append("a spec file changed alongside a src/ change without a 'spec-change:' note (FR-010/FR-011)")
    return problems


def _pr_rule_problems() -> list[str]:
    return pr_rule_problems(changed_files(), *pr_state(), issue_exists_in_repo)


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
    traced = identifiers_traced_by_tests(prefix) | identifiers_justified(prefix)
    untraced = [identifier for identifier in ids if identifier not in traced]
    print(f"Feature {prefix}: {len(ids)} requirement id(s) in {rel}; {len(ids) - len(untraced)} traced "
          f"(a feature-scoped test reference or a justification in traceability.md).")
    return [f"requirement {identifier} is not traced for feature {prefix} "
            f"(reference it as '{prefix}/{identifier}' or in a test file marked FEATURE = \"{prefix}\", "
            f"or justify it in specs/{prefix}-*/traceability.md)" for identifier in untraced]


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
