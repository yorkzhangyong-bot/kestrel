# Research: Human-Approved Spec Workflow

Phase 0 decisions. The clarify session (spec §Clarifications, 2026-10-29) already settled: CI enforces the
spec-PR reference; the spec-mode check reads the whole feature directory; IDs are `FR-###`/`SC-###` (zero-padded,
gaps allowed). The items below resolve the remaining design unknowns.

## 1. Detecting a spec-only pull request

- **Decision**: Compute the PR's changed files with `git diff --name-only origin/<base>...HEAD` and classify the
  PR as **spec-only** when none of those paths start with `src/`, `tests/`, `ui/`, or `scripts/`. Do this in one
  fast `classify` job that exposes `spec_only` as a job output.
- **Rationale**: Matches FR-002 exactly (classification depends only on the absence of code-directory changes, so
  a spec PR may also touch `.github/` or `docs/`). A single classify job keeps the rule in one place; the three
  gate jobs read `needs.classify.outputs.spec_only`.
- **Alternatives considered**: Computing the diff independently inside each gate job (more robust against a
  cross-job skip, but duplicates the rule three times); using the GitHub "paths" filter on the workflow trigger
  (can't express "no code dirs" as a single gate and would skip whole jobs, tripping the required-check gotcha
  below).

## 2. Required checks must always report (the skip gotcha)

- **Decision**: `traceability`, `quality`, and `review` run on **every** PR and always report a result; on a
  spec-only PR the quality job reports success without running its heavy steps (each heavy step is guarded by
  `if: needs.classify.outputs.spec_only != 'true'`). The `classify` job is written to always exit 0.
- **Rationale**: GitHub branch protection waits on a *required* status check by job name. A job that is skipped
  (never runs) never reports, so protection would block forever. Running the job and short-circuiting to success
  keeps the required check green (FR-006). Making `classify` always succeed guarantees the three jobs that
  `need` it are never skipped.
- **Alternatives considered**: Marking the quality job itself conditional (`if:` at job level) — this makes it
  "skipped", which does **not** satisfy a required check; rejected.

## 3. CODEOWNERS and branch protection

- **Decision**: Add `.github/CODEOWNERS` with `/specs/ @<owner>` (and a catch-all `* @<owner>` so every PR needs
  the owner). Document in `docs/branch-protection.md` the exact settings to apply by hand on `master`: require a
  pull request before merging; require at least 1 approving review; require review from Code Owners; require
  status checks to pass with "Require branches to be up to date"; list `traceability`, `quality`, `review` as the
  required checks; do not allow bypass.
- **Rationale**: FR-007/FR-008. GitHub does not let a repository set its own branch protection from committed
  files — it is an admin setting applied through the UI or the REST API by the owner — so the repo can only ship
  the `CODEOWNERS` file plus a precise manual guide (FR-013).
- **Alternatives considered**: A rulesets-as-code tool/action to apply protection — rejected as a new dependency
  and out of scope (Principle X; the feature explicitly keeps protection manual).
- **Note**: The required-check **names** must match the job names in `qa.yml` exactly, or protection waits on a
  check that never appears. The guide calls this out.

## 4. Reading the PR body and head/base refs in CI

- **Decision**: The spec-change rule (FR-010/011) and the spec-PR-reference rule (FR-009) read the PR body from
  the event payload (`github.event.pull_request.body`, passed to the checker as an environment variable) and the
  changed paths from `git diff` against `origin/<base>`. The checker treats a missing body as empty.
- **Rationale**: The `pull_request` event carries the body; passing it as an env var keeps `check_traceability.py`
  unit-testable (the pure helpers take `changed_files` and `pr_body` as arguments). `GITHUB_HEAD_REF`/
  `GITHUB_BASE_REF` already drive the existing traceability checker.
- **Alternatives considered**: Querying the body via `gh pr view` inside the script — rejected; it couples the
  pure logic to the network and is harder to test than an injected string.

## 5. Spec-mode check: scope, format, and what counts as an orphan

- **Decision**: `check_spec.py` reads every `*.md` under the feature directory (`spec.md`, `plan.md`, `tasks.md`,
  `contracts/*`), collects **definitions** (a line matching `- **FR-### / SC-###**`) and **references** (any
  `FR-###`/`SC-###` token). It fails if: an identifier is not well-formed (`FR`/`SC` + exactly three digits), a
  definition ID appears twice (duplicate), or a referenced ID has no definition (orphan). Numbering gaps are
  allowed. It prints each offending ID and exits non-zero.
- **Rationale**: Directly from the clarifications. Reading the whole feature directory catches a dangling
  reference in `plan.md`/`tasks.md`, not just in `spec.md`. The "definition = `- **FR-###**`" convention matches
  how the existing specs and `check_traceability.py` already treat definitions, so there is one shared notion of
  a requirement ID.
- **Alternatives considered**: Validating only `spec.md` (misses plan/tasks orphans); treating "orphan" as a
  defined-but-unreferenced requirement (rejected in clarify — orphan means a dangling reference).

## 6. Two checkers rather than one

- **Decision**: Keep `check_spec.py` pure and spec-only; put the implementation-PR rules (tests-traceability +
  spec-change + spec-PR-reference) in the existing `check_traceability.py`. The `traceability` job runs
  `check_spec.py` when `spec_only`, else `check_traceability.py`.
- **Rationale**: `check_spec.py` stays a pure file-reader (easy to unit-test, reusable locally). The PR rules
  belong with the traceability checker that already runs on code PRs and already reads the branch/diff. Each
  checker exposes small pure functions so the rules are unit-tested without GitHub.
- **Alternatives considered**: One mega-script with a `--mode` flag (muddier responsibilities, harder tests);
  three separate scripts (more surface, no benefit).

## 7. Switching the review checklist for spec PRs

- **Decision**: The `review` job has two Claude Code Action steps, one gated on `spec_only == true` pointing its
  prompt at `.github/review/spec-checklist.md` and the feature spec, the other (the existing step) pointing at
  `checklist.md`. Both are followed by the shared verdict-enforcement step that fails on `VERDICT: FAIL`.
- **Rationale**: The prompt text is static per step, so a conditional pair is simpler and more predictable than
  asking the model to detect the PR type and pick a checklist. The spec checklist targets spec-level defects
  (ambiguity, missing/weak success criteria, untestable requirements, constitution conflicts) per FR-004.
- **Alternatives considered**: One step with a templated checklist path — Actions expression interpolation into
  `claude_args`/`prompt` is possible but makes the step harder to read than two explicit steps.

## 8. Bootstrap / rollout order

- **Decision**: This feature's own rollout follows the cycle it defines: this spec PR (specs/ + docs/ only) is
  approved and merged first; a later implementation PR adds `check_spec.py`, the `qa.yml` changes,
  `CODEOWNERS`, `spec-checklist.md`, the docs, and the tests; the owner then applies `branch-protection.md`
  manually. The workflow governs features 006 onward and is not applied retroactively to 001–005.
- **Rationale**: Dogfoods the feature and matches the spec's Bootstrap edge case. Branch protection is applied
  after the workflow jobs exist so the required-check names resolve.
- **Alternatives considered**: Applying branch protection before the jobs exist — rejected; protection would wait
  on check names that do not yet report.
