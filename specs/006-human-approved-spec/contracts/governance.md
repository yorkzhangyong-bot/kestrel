# Contract: workflow jobs, CODEOWNERS, and branch protection

## `qa.yml` jobs on a pull request

A `classify` job runs first and outputs `spec_only`. The three **required** jobs depend on it, always run, and
always report a result.

| Job | Spec-only PR (`spec_only == true`) | Implementation PR (`spec_only == false`) |
|---|---|---|
| `classify` | computes `spec_only`, always exits 0 (not a required check) | same |
| `traceability` | run `check_spec.py` (spec-mode) | run `check_traceability.py` (tests-traceability + spec-change + Spec-PR rules) |
| `quality` | report **success** without running lint/type/tests/coverage/scans (FR-005, FR-006) | run the full quality steps |
| `review` | Claude Code Action against `.github/review/spec-checklist.md` + the spec; then the verdict gate | Claude Code Action against `.github/review/checklist.md`; then the verdict gate |
| `notify` | on any failure, email failed jobs (unchanged; not a required check) | same |

- The `review` verdict gate is the existing step: it reads the latest PR comment and fails on `VERDICT: FAIL`
  (a severe finding), for both checklists.
- Required status checks (names must match exactly): **`traceability`**, **`quality`**, **`review`**.

## `.github/CODEOWNERS`

```text
# The repository owner approves every pull request; specs in particular.
*         @yorkzhangyong-bot
/specs/   @yorkzhangyong-bot
```

- `@yorkzhangyong-bot` is the repository owner's GitHub login.
- Requires "Require review from Code Owners" in branch protection to have effect.

## `docs/branch-protection.md` — manual settings on `master`

GitHub does not let a repository configure its own protection; the owner applies these by hand (Settings →
Branches → add rule for `master`, or the REST API):

- Require a pull request before merging.
- Require approvals: **1**.
- Require review from **Code Owners**.
- Dismiss stale approvals when new commits are pushed (recommended).
- Require status checks to pass before merging, with **Require branches to be up to date**.
- Required status checks: `traceability`, `quality`, `review`.
- Do not allow bypassing the above (apply to administrators).
- (Optional) Require conversation resolution before merging.

The guide notes that the required-check names must match the `qa.yml` job names exactly, and that protection
should be applied only after the workflow with those jobs is merged (so the checks exist to be selected).

## Documentation of the cycle (FR-012)

README and `docs/qa-pipeline.md` describe:

```text
specify → clarify → spec PR (specs/ + docs/ only) → human approval → merge
       → plan / tasks / implement → implementation PR (Spec-PR: #n) → four gates → human merge
```
