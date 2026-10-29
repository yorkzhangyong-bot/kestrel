# Data Model: Human-Approved Spec Workflow

This feature persists no data; the "model" is the set of values the checkers and the workflow derive from a pull
request and validate. Shapes are described so the pure helpers can be unit-tested in isolation.

## PR classification

Derived once per PR from the changed file paths.

| Field | Type | Meaning |
|---|---|---|
| `changed_files` | list[str] | Repo-relative paths changed in the PR (`git diff --name-only origin/<base>...HEAD`). |
| `spec_only` | bool | True when **no** path in `changed_files` starts with `src/`, `tests/`, `ui/`, or `scripts/`. |

**Rule**: `spec_only = not any(p.startswith(("src/", "tests/", "ui/", "scripts/")) for p in changed_files)`. A PR
that touches only `specs/`/`docs/` (or also `.github/`) is spec-only; any code-directory change makes it an
implementation PR.

## Requirement identifier

Collected by `check_spec.py` from every `*.md` in a feature directory.

| Field | Type | Meaning |
|---|---|---|
| `prefix` | `"FR"` \| `"SC"` | Requirement family. |
| `number` | str | Exactly three digits, zero-padded (e.g. `007`). |
| `role` | `"definition"` \| `"reference"` | A **definition** is a line matching `- **FR-### / SC-###**: …`; any other occurrence of the token is a **reference**. |
| `location` | str | `file:line` for the message. |

**Validation rules** (FR-003):

- **Well-formed**: the token matches `^(FR|SC)-\d{3}$`. Anything like `FR-7` or `FR-0001` is malformed.
- **Unique**: each identifier has at most one definition across the feature directory; a second definition is a duplicate.
- **No orphan reference**: every referenced identifier has a definition somewhere in the feature directory.
- **Gaps allowed**: missing numbers (e.g. FR-002 then FR-004) are not an error.

## PR-description markers

Read from the pull request body (passed to the checker as an env var; missing body = empty string).

| Marker | Pattern (case-insensitive, line-anchored) | Used by |
|---|---|---|
| Spec-PR reference | `^Spec-PR:\s*#\d+` | FR-009 — required on implementation PRs. |
| Spec-change note | `^spec-change:\s*\S` | FR-010/011 — required when an implementation PR also edits a spec file. |

## Implementation-PR rule outcomes

Evaluated by `check_traceability.py` only when `spec_only` is false.

| Rule | Inputs | Fails when |
|---|---|---|
| Tests-traceability (existing) | spec IDs, `tests/` | A spec FR/SC is unreferenced by any test (existing behaviour, unchanged). |
| Spec-change (FR-010/011) | `changed_files`, `pr_body` | `changed_files` contains both a `specs/**` file and a `src/**` file, and `pr_body` has no `spec-change:` line. |
| Spec-PR reference (FR-009) | `pr_body` | The PR changed code (it is an implementation PR) and `pr_body` has no `Spec-PR: #<n>` line. |

## Governance entities (platform, not code)

- **CODEOWNERS entry**: maps a path pattern (`/specs/`, and `*`) to the repository owner; GitHub uses it to require a code-owner review.
- **Branch-protection rule** (manual, on `master`): require a PR, ≥1 approving review, review from Code Owners, and the required status checks `traceability` / `quality` / `review`, with branches up to date and no bypass. Described in `contracts/governance.md` and `docs/branch-protection.md`; not represented in the repository as enforceable config.
- **Spec review standard**: `.github/review/spec-checklist.md` — the categories the spec review applies (ambiguity, missing/weak success criteria, untestable requirements, constitution conflicts).
