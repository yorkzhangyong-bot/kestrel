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

## Pull-request state, read live (added 2026-11-24; revised after review round 1 and the owner's review of PR #50)

`check_traceability.py` fetches `gh pr view <PR_NUMBER> --repo <GITHUB_REPOSITORY> --json body,labels` at
evaluation time (the job's own token, on a job limited to `contents: read`, `pull-requests: read` and `issues: read`) and parses it with the pure `parse_pr_state(raw) -> (body, labels)`; any failure of the read (a missing
`PR_NUMBER`, a non-zero exit, a timeout, no `gh` on the path, any other exception, unparsable JSON) is `("", [])` —
fail-closed for the honest path (FR-018).

| Field | Type | Meaning |
|---|---|---|
| `body` | str | `body` of the JSON when it is a string, else `""`. |
| `labels` | list[str] | The `name` of every element of `labels` when every element is an object with a string `name`; any other shape gives `[]`. Compared case-insensitively (FR-017). |
| reason label | `"refactor"` \| `"bugfix"` | The label named after the reason keyword; it must be present and the other must be absent (FR-015, FR-016). |

The bugfix issue lookup (FR-024): once every other condition holds on the bugfix path, one call
`gh api repos/<GITHUB_REPOSITORY>/issues/<n>`, parsed by the pure `parse_issue_lookup(raw, repository, number) -> bool`;
the pure rule receives it as an injected `issue_exists(number) -> bool`.

| Field | Type | Meaning |
|---|---|---|
| `number` | int | Must equal the looked-up number (a followed transfer redirect changes it). |
| `pull_request` | key | Present on a pull request: the number is not an issue → fail. |
| `repository_url` | str | Must end with `/repos/<GITHUB_REPOSITORY>` (case-insensitive): an issue elsewhere, or transferred, fails. |
| `state` | str | Ignored: open or closed both pass. |
| any failure | — | A non-zero exit, a timeout, no `gh` on the path, invalid JSON, a non-object, a rate limit → `False` (fail closed), with a notice naming only the number. |

## Recheck relevance (FR-019)

The recheck workflow (`qa-recheck.yml`) listens to `pull_request` `edited`, `labeled` and `unlabeled`; its job runs only
for a relevant event and then re-runs the traceability job of the newest pipeline run for the current head commit.

| Event action | Payload field | Relevant when |
|---|---|---|
| `edited` | `changes.body` | present (the body changed); a title or base-branch edit carries no `changes.body` → not relevant. |
| `labeled` / `unlabeled` | `label.name` | `refactor` or `bugfix` (compared ignoring case); any other label → not relevant. |
| anything else | — | not relevant. |

Recheck outcomes (one 30-minute budget; the pure mirror `next_action(run_status, rerun_status, elapsed, budget)`
lives in the reference probe and in `scripts/qa_recheck.py`; `rerun_status` is `None` / `"accepted"` /
`"refused"`, never a literal HTTP status code): before requesting a re-run, `already_fresh(attempt_started_at,
recheck_created_at)` skips it and exits 0 when the traceability job's latest attempt already started after this
recheck run was created — no run, or a run in `action_required` / `waiting` → exit 0 (nothing to refresh); `queued`
/ `in_progress` → wait; `completed` → request the re-run; accepted → exit 0. GitHub's re-run endpoint documents
only `201` and `403`, and returns the same `403` whether another attempt is already running or the refusal is
final, so a refusal is classified by re-reading the run, never by that code: not `completed` → wait and retry;
still `completed` → one fixed-text stale-result comment (never containing `VERDICT: PASS`/`VERDICT: FAIL`), exit 1.
The budget exhausted while waiting or retrying → the same comment, exit 1. No concurrency group: an irrelevant
event's run only skips its own job.

**API failures (review round 3)**: every client call either returns its declared value or raises
`RecheckApiError` after its own timeout — never a silent `None`/empty standing in for a failure. `get_latest_run`'s
`None` and `get_job`'s `None` each mean only a genuinely empty, successful result (no run; no `traceability` job),
never a failed call. A `RecheckApiError` from steps 1–3 or the post-refusal re-read is retried at the next poll
within the same budget (`run_status = "error"`); a budget spent this way ends in the same stale-result comment,
reason `error` rather than `timeout`, never in exit 0. A completed run with no `traceability` job (`run_status =
"no_job"`) goes straight to the comment — retrying cannot make a job appear. `already_fresh` never raises: a
missing or unparsable `started_at`/`created_at` makes it return `False`, so the re-run POST is sent rather than
skipped. The script's entry point catches any other exception and still attempts the comment (with its one retry)
before exit 1.

## Implementation-PR rule outcomes

Evaluated by `check_traceability.py` only when `spec_only` is false. The Spec-PR declaration rule further
requires a `src/` or `ui/` change (`changes_app_code`), on any branch; a tests-only or scripts-only PR is
not evaluated for it.

| Rule | Inputs | Fails when |
|---|---|---|
| Tests-traceability (existing) | spec IDs, `tests/` | A spec FR/SC is unreferenced by any test (existing behaviour, unchanged). |
| Spec-change (FR-010/011) | `changed_files`, `pr_body` | `changed_files` contains both a `specs/**` file and a `src/**` file, and `pr_body` has no `spec-change:` line. |
| Spec-PR declaration (FR-009, FR-015, FR-016) | `pr_body`, `labels` | The PR changes `src/` or `ui/` and `pr_body` has neither a `Spec-PR: #<n>` line nor a complete `Spec-PR: none` declaration — or the declaration conflicts (a numbered line beside a `none`-valued line or a reason line), the honest path carries more than one `Spec-PR:` line or one whose value is not exactly `none`, the reason line is missing, doubled or malformed, its label is missing, the other reason's label is present, or — on the bugfix path, after all of that holds — the number is not an issue of this repository (FR-024). Evaluated by the pure `pr_rule_problems(changed_files, pr_body, labels, issue_exists)`. |

## Governance entities (platform, not code)

- **CODEOWNERS entry**: maps a path pattern (`/specs/`, and `*`) to the repository owner; GitHub uses it to require a code-owner review.
- **Branch-protection rule** (manual, on `master`): require a PR, ≥1 approving review, review from Code Owners, and the required status checks `traceability` / `quality` / `review`, with branches up to date and no bypass. Described in `contracts/governance.md` and `docs/branch-protection.md`; not represented in the repository as enforceable config.
- **Spec review standard**: `.github/review/spec-checklist.md` — the categories the spec review applies (ambiguity, missing/weak success criteria, untestable requirements, constitution conflicts).
