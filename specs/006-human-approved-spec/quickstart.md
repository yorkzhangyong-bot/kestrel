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

## 6. Honest path for a refactor or bug-fix PR (GitHub, added 2026-11-24; revised after the reviews and the owner's review of PR #50)

Prerequisites: the labels `refactor` and `bugfix` exist in the repository
([docs/branch-protection.md](../../docs/branch-protection.md)); the feature branch carries the new `qa.yml`
(default pull-request events; `PR_NUMBER` and `GH_TOKEN` on a traceability job limited to `contents: read`,
`pull-requests: read` and `issues: read`), the new `qa-recheck.yml` (`edited`, `labeled`, `unlabeled` on `master`;
`actions: write`, `contents: read`, `pull-requests: write`; no concurrency group), its script `scripts/qa_recheck.py`,
and the new `check_traceability.py` — merged or not: a `pull_request` run uses
the workflow files from the PR's own merge commit, so a PR based on the feature branch runs the new gate and the
new recheck before the implementation PR merges. The draft must be **mergeable**: GitHub runs no `pull_request`
workflow on a PR with a merge conflict, so base the scratch branch on a feature branch that is up to date with
`master`.

Vehicle: a throwaway **draft** PR to `master` from a scratch branch based on the feature branch — a name without a
numeric prefix (for example `probe/honest-path`), so only the Spec-PR rule is under test. On that branch first
restore `specs/` to master's version with `git checkout --no-overlay origin/master -- specs/` (an overlay checkout,
the default, keeps files the branch added under `specs/`), add one trivial change under `src/` (a comment), commit
both together, and confirm that `git diff --name-only origin/master...HEAD -- specs/` prints nothing before opening
the draft — so its diff holds no spec file and the spec-change rule stays out of the way until step 8. The numbers
used below: `#37`, a real, closed issue of this repository (the bugfix pass step leaves a "mentioned this"
cross-reference on it — the only trace the throwaway leaves); `#999999`, which no issue or pull request has; `#49`,
a pull request. Its description carries exactly:

```text
Spec-PR: none
Spec-PR-reason: refactor
```

1. Create it with `gh pr create --draft --label refactor --body-file <file>`: the `opened` event starts the
   pipeline, the `labeled` event starts the recheck, which waits for that pipeline run to complete and re-runs its
   `traceability` job; the re-run reads the label live and passes. (If the `opened` run read the state before the
   label landed it failed and `notify` emailed once; the re-run is the newer, passing attempt.) The recheck shows as
   its own, non-required check. The `review` check is irrelevant here: the Claude action refuses a PR that changes
   a workflow file, so it passes only while `SKIP_AI_REVIEW=true`.
2. Remove the label (no push): the recheck re-runs `traceability`, which fails because the `refactor` label is
   missing, and the message names the three accepted forms; `quality` and `review` keep their results. Add the label
   back: it re-runs again and passes. Then, in one action, remove `refactor` and add an unrelated label
   (`gh pr edit --remove-label refactor --add-label documentation`): two events — the `unlabeled` recheck re-runs
   `traceability`, which turns red; the `labeled` run skips its job and cancels nothing. Swap them back in one
   action (`--remove-label documentation --add-label refactor`): it passes again. Then, in one action, remove
   `refactor` and add `bugfix` instead (`gh pr edit --remove-label refactor --add-label bugfix`, the description
   still reading `Spec-PR-reason: refactor`): two *relevant* events this time — both the `unlabeled` and the
   `labeled` recheck start, and one of their re-run requests may be refused (both land within seconds of the same
   run completing); either way neither recheck posts the stale-result comment and both exit `0` — a refused one
   re-reads the run, sees it is not yet `completed`, and waits and retries rather than mistaking the refusal for a
   final one (the re-read path itself is `tests/unit/test_qa_recheck.py`'s, T034, to prove; with 30-second polling
   and the freshness pre-check, the second recheck usually sees the run already in progress, or already fresh,
   before it ever posts). `traceability` re-runs and turns red (the reason line still says `refactor`, and the
   `refactor` label is now gone). Swap back to `refactor` alone (`--remove-label bugfix --add-label refactor`): it
   passes again.
3. Re-run the `traceability` job of the run's **latest** attempt (Actions page, or `gh run rerun <run> --job
   <latest traceability job id>`): it reads the current state (label present) and passes — a re-run judges now,
   not the event that first triggered it (FR-018). (Revised 2026-11-25, found live, T031: GitHub refuses
   `gh run rerun` on an older attempt's job id — "job cannot be rerun" — only the latest attempt's own jobs can be
   re-run; step 2a already shows the same live-read property, since the run was triggered by `opened` with the
   `refactor` label already on and its own `labeled`-triggered re-run still read the live, current labels rather
   than that triggering snapshot.)
4. Edit the description's body to `Spec-PR-reason: bugfix: #37` (no push): the recheck re-runs `traceability`; with
   only the `refactor` label on, it fails because the `bugfix` label is missing (the first failed condition is the
   one reported). Add `bugfix` (both labels on): it fails because the `refactor` label contradicts the reason.
   Remove `refactor`: it passes — the lookup found `#37`, a closed issue of this repository (FR-024).
5. Edit the body to `Spec-PR-reason: bugfix: #999999`: it fails — `#999999` is not an issue of this repository.
   Edit it to `Spec-PR-reason: bugfix: #49`: it fails the same way — a pull request is not an issue. Edit it back to
   `#37`: it passes.
6. Edit only the title: a recheck run starts with its job skipped; `traceability`, `quality` and `review` keep their
   results. Add a label other than `refactor` and `bugfix` (for example `documentation`), then remove it: the same —
   nothing re-runs (FR-019). (The stale-result cases — a fork, the 50-re-run cap, a timeout — are not provoked here;
   their comment and the merge rule are in the spec's Assumptions.)
7. Add a `Spec-PR: #999999` line beside the `none` line: it fails as a conflict. Replace both new lines by
   `Spec-PR: #999999` alone, with the `bugfix` label still on: it passes — labels and other `Spec-PR:` values are
   ignored on the numbered form, and the number is not looked up (SC-009). Restore the two honest-path lines
   (`Spec-PR: none`, `Spec-PR-reason: refactor`), remove the `bugfix` label, add the `refactor` label: it passes
   again.
8. Push a spec edit (any file under `specs/`) with no `spec-change:` line: the pipeline runs on `synchronize` and
   fails on the spec-change rule (FR-010), as any implementation PR would — a distinct observation, since the
   draft's diff held no spec file until now.
9. Close the draft PR unmerged and delete the scratch branch.

Locally, without GitHub, the same matrix is the unit test `tests/unit/test_check_traceability.py` (T021) over the
pure helpers in [contracts/pr-rules.md](contracts/pr-rules.md), with the description, the labels and a stubbed
issue lookup passed as plain arguments.

## Success criteria mapping

| Scenario | Validates |
|---|---|
| 1, 2 | FR-003, FR-014, SC-002, SC-006 |
| 3 | FR-002, FR-004, FR-005, FR-006, SC-001 |
| 4 | FR-009, FR-010, FR-011, SC-003, SC-007 |
| 5 | FR-007, FR-008, FR-013, SC-004 |
| 6 | FR-009, FR-015, FR-016, FR-017, FR-018, FR-019, FR-020, FR-021, FR-022, FR-024, SC-007, SC-008, SC-009, SC-010 |
| docs/qa-pipeline.md, docs/branch-protection.md, CLAUDE.md, docs/roadmap.md | FR-021, FR-023 |
| README + docs/qa-pipeline.md | FR-012, SC-005 |
