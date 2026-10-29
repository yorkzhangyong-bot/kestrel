# Quickstart: Human-Approved Spec Workflow

How to validate the feature. The automated parts run under pytest; the end-to-end GitHub flow is validated by the
manual scenarios below (it depends on PR events and branch protection that cannot run in pytest).

## Prerequisites

- Python 3.12 and `uv` (see the root README).
- For the GitHub scenarios: the implementation PR merged, and `docs/branch-protection.md` applied to `master`.

## 1. Spec-mode checker (local)

```bash
# Passes on a well-formed feature directory:
uv run python scripts/check_spec.py specs/006-human-approved-spec        # exit 0

# Infers the feature from the current branch when no path is given:
GITHUB_HEAD_REF=006-human-approved-spec uv run python scripts/check_spec.py   # exit 0
```

Expected: a one-line summary of FR/SC counts, exit 0. Temporarily introducing a duplicate `- **FR-003**` line, a
reference to an undefined `SC-099`, or a malformed `FR-7` makes it print the offending ID and exit 1.

## 2. Unit tests

```bash
uv run pytest tests/unit/test_check_spec.py tests/unit/test_check_traceability.py -q
```

Expected: green. Covers well-formed / duplicate / orphan / malformed / clean spec (check-spec), and
classification + spec-change + Spec-PR-reference helpers (traceability). See
[contracts/check-spec.md](contracts/check-spec.md) and [contracts/pr-rules.md](contracts/pr-rules.md).

## 3. Spec-only PR (GitHub)

1. On a feature branch, commit only `specs/<nnn>-*/…` and `docs/…` and open a PR to `master`.
2. Expected on the PR:
   - `classify` marks it spec-only.
   - `traceability` runs the spec-mode check (not the tests-traceability check).
   - `quality` reports **success without running** lint/type/tests/coverage/scans.
   - `review` posts a comment against `.github/review/spec-checklist.md` ending in `VERDICT: PASS`/`FAIL`.
   - Merge is blocked until a code owner approves (branch protection).

## 4. Implementation PR rules (GitHub)

Open a PR that changes code (`src/`, `tests/`, …):

- **Spec-PR reference** — with no `Spec-PR: #<n>` line in the description, `traceability` fails; add the line and
  it passes.
- **Spec-change** — if the same PR also edits a `specs/**` file with no `spec-change: <reason>` line, `traceability`
  fails; add the line and it passes. A PR that changes code but no spec file needs no `spec-change:` note.

## 5. Branch protection (one-time, manual)

Apply [docs/branch-protection.md](../../docs/branch-protection.md) to `master`, then confirm: a PR cannot merge
without a code-owner approval and passing `traceability`, `quality`, `review`. See
[contracts/governance.md](contracts/governance.md) for the exact settings and required-check names.

## Success criteria mapping

| Scenario | Validates |
|---|---|
| 1, 2 | FR-003, FR-014, SC-002, SC-006 |
| 3 | FR-002, FR-004, FR-005, FR-006, SC-001 |
| 4 | FR-009, FR-010, FR-011, SC-003, SC-007 |
| 5 | FR-007, FR-008, FR-013, SC-004 |
| README + docs/qa-pipeline.md | FR-012, SC-005 |
