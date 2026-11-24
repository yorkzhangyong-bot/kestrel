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

- **Spec-PR declaration** (only when `src/` or `ui/` changed, on any branch) — with no `Spec-PR:` line in the
  description, `traceability` fails and the message names the accepted forms; add `Spec-PR: #<n>` and it
  passes. A tests-only or scripts-only PR needs no line (the rule is not evaluated). The `Spec-PR: none`
  form is scenario 6. The gate reads the raw description: a keyed line inside an HTML comment or other
  markup counts like any other line.
- **Spec-change** — if the same PR also edits a `specs/**` file with no `spec-change: <reason>` line, `traceability`
  fails; add the line and it passes. A PR that changes code but no spec file needs no `spec-change:` note.

## 5. Branch protection (one-time, manual)

Apply [docs/branch-protection.md](../../docs/branch-protection.md) to `master`, then confirm: a PR cannot merge
without a code-owner approval and passing `traceability`, `quality`, `review`. See
[contracts/governance.md](contracts/governance.md) for the exact settings and required-check names.

## 6. Honest path for a refactor or bug-fix PR (GitHub, added 2026-11-24; revised after review rounds 1 and 2)

Prerequisites: the labels `refactor` and `bugfix` exist in the repository
([docs/branch-protection.md](../../docs/branch-protection.md)); the feature branch carries the new `qa.yml` (the
six pull-request events; `PR_NUMBER` and `GH_TOKEN` on a traceability job limited to `contents: read` and
`pull-requests: read`) and the new `check_traceability.py` — merged or not: a `pull_request` run uses the workflow
file from the PR's own merge commit, so a PR based on the feature branch runs the new gate before the
implementation PR merges. The draft must be **mergeable**: GitHub runs no `pull_request` workflow on a PR with a
merge conflict, so base the scratch branch on a feature branch that is up to date with `master`.

Vehicle: a throwaway **draft** PR to `master` from a scratch branch based on the feature branch — a name without a
numeric prefix (for example `probe/honest-path`), so only the Spec-PR rule is under test. On that branch first
restore `specs/` to master's version with `git checkout --no-overlay origin/master -- specs/` (an overlay checkout,
the default, keeps files the branch added under `specs/`), add one trivial change under `src/` (a comment), commit
both together, and confirm that `git diff --name-only origin/master...HEAD -- specs/` prints nothing before opening
the draft — so its diff holds no spec file and the spec-change rule stays out of the way until step 6. Every issue or PR number written below is one that does not exist (`#999999`), so the throwaway PR leaves
no cross-reference on a real issue or pull request. Its description carries exactly:

```text
Spec-PR: none
Spec-PR-reason: refactor
```

1. Create it with `gh pr create --draft --label refactor --body-file <file>`: an `opened` run and a `labeled` run
   start on the same commit; both read the description and labels live, so both pass the Spec-PR rule. (If the
   `opened` run reads before the label lands it fails and `notify` emails once; the `labeled` run that follows is
   the newer, passing result.) The `review` check is irrelevant here: the Claude action refuses a PR that changes a
   workflow file, so it passes only while `SKIP_AI_REVIEW=true`.
2. Remove the label (no push): the pipeline runs again on `unlabeled`; `traceability` fails because the `refactor`
   label is missing, and the message names the three accepted forms. Add it back: it runs again and passes.
3. Re-run the failed run of step 2 from the Actions page: it reads the current state (label present) and passes —
   a re-run judges now, not the event that first triggered it (FR-018).
4. Edit the description to `Spec-PR-reason: bugfix: #999999` (no push): the pipeline runs on `edited`; with only
   the `refactor` label on, it fails because the `bugfix` label is missing (the first failed condition is the one
   reported). Add `bugfix` (both labels on): it fails because the `refactor` label contradicts the reason. Remove
   `refactor`: it passes; the issue number is not looked up.
5. Add a `Spec-PR: #999999` line beside the `none` line: it fails as a conflict. Replace both new lines by
   `Spec-PR: #999999` alone, with the `bugfix` label still on: it passes — labels and other `Spec-PR:` values are
   ignored on the numbered form (SC-009). Restore the two honest-path lines (`Spec-PR: none`,
   `Spec-PR-reason: refactor`), remove the `bugfix` label, add the `refactor` label: it passes again.
6. Push a spec edit (any file under `specs/`) with no `spec-change:` line: it fails on the spec-change rule
   (FR-010), as any implementation PR would — a distinct observation, since the draft's diff held no spec file
   until now.
7. Close the draft PR unmerged and delete the scratch branch.

Locally, without GitHub, the same matrix is the unit test `tests/unit/test_check_traceability.py` (T021) over the
pure helpers in [contracts/pr-rules.md](contracts/pr-rules.md), with the description and the labels passed as plain
arguments.

## Success criteria mapping

| Scenario | Validates |
|---|---|
| 1, 2 | FR-003, FR-014, SC-002, SC-006 |
| 3 | FR-002, FR-004, FR-005, FR-006, SC-001 |
| 4 | FR-009, FR-010, FR-011, SC-003, SC-007 |
| 5 | FR-007, FR-008, FR-013, SC-004 |
| 6 | FR-009, FR-015, FR-016, FR-017, FR-018, FR-019, FR-020, FR-021, FR-022, SC-007, SC-008, SC-009, SC-010 |
| docs/qa-pipeline.md, docs/branch-protection.md, CLAUDE.md, docs/roadmap.md | FR-021, FR-023 |
| README + docs/qa-pipeline.md | FR-012, SC-005 |
