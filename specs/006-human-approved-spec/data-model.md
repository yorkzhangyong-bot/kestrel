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

Read from the raw pull request body, fetched live (see below), exactly as today — text inside an HTML comment or
other markup counts like any other line; a keyed line starts in column 1.

| Marker | Pattern (case-insensitive, line-anchored) | Used by |
|---|---|---|
| Spec-PR reference (numbered form) | `^Spec-PR:\s*#\d+` | FR-009 — one of the two accepted declarations on a PR that changes `src/` or `ui/`; grammar unchanged (text after the number is tolerated). |
| Any `Spec-PR:` line (value captured) | `^Spec-PR:[ \t]*(.*?)[ \t\r]*$` | FR-015, FR-016 — on the honest path exactly one such line, value exactly `none` (case-insensitive); a value starting with `none` beside a numbered line is a conflict. |
| Spec-PR reason line (value captured) | `^Spec-PR-reason:[ \t]*(.*?)[ \t\r]*$` | FR-015 — exactly one, only beside `Spec-PR: none`; its value must match `^(?:refactor\|bugfix:[ \t]*#[0-9]+)$` (case-insensitive, FR-017); any other value is a malformed reason (FR-016). |
| Spec-change note | `^spec-change:\s*\S` | FR-010/011 — required when an implementation PR also edits a spec file. |

## Pull-request state, read live (added 2026-11-24; revised after review round 1)

`check_traceability.py` fetches `gh pr view <PR_NUMBER> --repo <GITHUB_REPOSITORY> --json body,labels` at
evaluation time (the job's own token, on a job limited to `contents: read` and `pull-requests: read`) and parses it with the pure `parse_pr_state(raw) -> (body, labels)`; any failure of the read (a missing
`PR_NUMBER`, a non-zero exit, a timeout, no `gh` on the path, any other exception, unparsable JSON) is `("", [])` —
fail-closed for the honest path (FR-018).

| Field | Type | Meaning |
|---|---|---|
| `body` | str | `body` of the JSON when it is a string, else `""`. |
| `labels` | list[str] | The `name` of every element of `labels` when every element is an object with a string `name`; any other shape gives `[]`. Compared case-insensitively (FR-017). |
| reason label | `"refactor"` \| `"bugfix"` | The label named after the reason keyword; it must be present and the other must be absent (FR-015, FR-016). |

## Implementation-PR rule outcomes

Evaluated by `check_traceability.py` only when `spec_only` is false. The Spec-PR declaration rule further
requires a `src/` or `ui/` change (`changes_app_code`), on any branch; a tests-only or scripts-only PR is
not evaluated for it.

| Rule | Inputs | Fails when |
|---|---|---|
| Tests-traceability (existing) | spec IDs, `tests/` | A spec FR/SC is unreferenced by any test (existing behaviour, unchanged). |
| Spec-change (FR-010/011) | `changed_files`, `pr_body` | `changed_files` contains both a `specs/**` file and a `src/**` file, and `pr_body` has no `spec-change:` line. |
| Spec-PR declaration (FR-009, FR-015, FR-016) | `pr_body`, `labels` | The PR changes `src/` or `ui/` and `pr_body` has neither a `Spec-PR: #<n>` line nor a complete `Spec-PR: none` declaration — or the declaration conflicts (a numbered line beside a `none`-valued line or a reason line), the honest path carries more than one `Spec-PR:` line or one whose value is not exactly `none`, the reason line is missing, doubled or malformed, its label is missing, or the other reason's label is present. Evaluated by the pure `pr_rule_problems(changed_files, pr_body, labels)`. |

## Governance entities (platform, not code)

- **CODEOWNERS entry**: maps a path pattern (`/specs/`, and `*`) to the repository owner; GitHub uses it to require a code-owner review.
- **Branch-protection rule** (manual, on `master`): require a PR, ≥1 approving review, review from Code Owners, and the required status checks `traceability` / `quality` / `review`, with branches up to date and no bypass. Described in `contracts/governance.md` and `docs/branch-protection.md`; not represented in the repository as enforceable config.
- **Spec review standard**: `.github/review/spec-checklist.md` — the categories the spec review applies (ambiguity, missing/weak success criteria, untestable requirements, constitution conflicts).
