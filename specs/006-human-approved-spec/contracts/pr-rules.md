# Contract: PR classification and implementation-PR rules

Spec-only classification and the two implementation-PR rules. The pure helpers take plain arguments so they are
unit-tested without GitHub; the scripts wrap them with the real diff and PR body.

## Classification (used by `qa.yml` / helper)

```text
is_spec_only(changed_files: list[str]) -> bool
```

- Returns `True` when no path starts with `src/`, `tests/`, `ui/`, or `scripts/`.
- The workflow's `classify` job computes `changed_files` from `git diff --name-only origin/<base>...HEAD` and
  exposes the result as the job output `spec_only` (`"true"`/`"false"`). The job always exits `0` so the gate
  jobs that depend on it never skip (FR-006).

## `check_traceability.py` additions (implementation PRs only)

The traceability job runs this script when `spec_only == false`. In addition to the existing
tests-traceability check, it evaluates two rules and fails (exit `1`) if either is violated.

### Spec-change rule (FR-010, FR-011)

```text
needs_spec_change_note(changed_files, pr_body) -> bool    # True => must have the note
spec_change_ok(changed_files, pr_body) -> bool
```

- A note is required when `changed_files` contains **both** a `specs/**` file and a `src/**` file.
- The note is a line in `pr_body` matching `^spec-change:\s*\S` (case-insensitive).
- Fails when the note is required but absent. Rationale surfaced in the message: an approved spec may not be
  edited inside a code PR without an explicit, reviewable acknowledgment.

### Spec-PR-reference rule (FR-009)

```text
has_spec_pr_reference(pr_body) -> bool
```

- On an implementation PR (code changed), `pr_body` MUST contain a line matching `^Spec-PR:\s*#\d+`
  (case-insensitive).
- Fails when absent.

### Inputs from the environment

- `changed_files`: from `git diff --name-only origin/$GITHUB_BASE_REF...HEAD`.
- `pr_body`: from `$PR_BODY` (the workflow passes `github.event.pull_request.body`); missing → treated as empty.

### Exit codes

- `0`: tests-traceability passes and both rules satisfied (or not applicable).
- `1`: any unreferenced requirement, a missing required spec-change note, or a missing Spec-PR reference; each
  failure is printed with the offending detail.

## Tests

`tests/unit/test_check_traceability.py` unit-tests the pure helpers: classification (code path vs spec-only);
spec-change required-and-missing → fail, required-and-present → pass, not-required → pass; Spec-PR reference
present/absent. (SC-003, SC-007)
