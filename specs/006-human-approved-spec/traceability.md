# Traceability: non-unit-testable requirements

The traceability gate (feature-scoped, feature 006) accepts a requirement id as traced if a test references it in
a feature-scoped way **or** it is justified here as a line `006/FR-00x: <justification>`
(see [scripts/check_traceability.py](../../scripts/check_traceability.py)). The requirements below are enforced
outside unit tests — by GitHub branch protection, `CODEOWNERS`, the workflow, or documentation — and are verified
manually via the scenarios in [quickstart.md](quickstart.md). Every other 006 requirement is covered by a unit
test (`tests/unit/test_check_spec.py`, `tests/unit/test_check_traceability.py`), scoped with `006/FR-00x` tokens.

- 006/FR-001: a human-followed convention; in practice an implementation PR references a merged spec PR (FR-009), and the cycle is documented in the README and docs/qa-pipeline.md. Verified via quickstart scenario 3.
- 006/FR-004: enforced by the review job's spec-only branch against .github/review/spec-checklist.md in qa.yml. Verified via quickstart scenario 3.
- 006/FR-005: enforced by the quality job's `spec_only` step guards in .github/workflows/qa.yml (heavy steps do not run, the job reports success). Verified via quickstart scenario 3.
- 006/FR-006: enforced by the classify job (always exits 0) and the quality success-without-running path, so required checks always report. Verified via quickstart scenario 3 and the required-check names in docs/branch-protection.md.
- 006/FR-007: enforced by .github/CODEOWNERS plus the "Require review from Code Owners" rule in branch protection. Verified via quickstart scenario 5.
- 006/FR-008: enforced by GitHub branch protection applied manually by the owner. Verified via quickstart scenario 5.
- 006/FR-012: satisfied by the README and docs/qa-pipeline.md, which describe the full cycle. Verified by reading them.
- 006/FR-013: satisfied by docs/branch-protection.md, which lists the exact manual settings. Verified via quickstart scenario 5.
- 006/SC-001: observed on a spec-only PR — the quality job reports success without running its heavy steps. Verified via quickstart scenario 3.
- 006/SC-004: enforced by GitHub branch protection; the guarantee holds once the owner has applied it. Verified via quickstart scenario 5.
- 006/SC-005: satisfied by the README, docs/qa-pipeline.md, and docs/branch-protection.md. Verified by following them end to end.

Added 2026-11-24 (the honest Spec-PR path; FR-015–FR-023, SC-008–SC-010 — the rest are unit-tested by
`tests/unit/test_check_traceability.py` with `006/FR-0xx` tokens, T021):

- 006/FR-018: the pure rule, the parse of the live read and the read's failure path are unit-tested (tests/unit/test_check_traceability.py, 006/FR-018: `spec_pr_rule_problems`, `parse_pr_state`, `pr_rule_problems`, and `pr_state` with the environment and `subprocess.run` monkeypatched — no `PR_NUMBER`, a non-zero `gh` exit, a timeout, no `gh` on the path, a notice without values); the read itself — `gh pr view <number> --json body,labels` with the job's token on a job limited to read permissions — is a subprocess in scripts/check_traceability.py, wired by .github/workflows/qa.yml (`PR_NUMBER`, `GH_TOKEN`, `permissions`). Verified live on the throwaway draft PR of quickstart scenario 6 (steps 1 and 3: overlapping runs and a manual re-run judge the current state).
- 006/FR-019: enforced by the pull-request event types in .github/workflows/qa.yml (`opened`, `synchronize`, `reopened`, `edited`, `labeled`, `unlabeled`), a workflow trigger no unit test can exercise. Verified live on the throwaway draft PR of quickstart scenario 6 (steps 2 and 4: a label change or a description edit alone re-runs the gate).
- 006/FR-021: the labels `refactor` and `bugfix` are created by the owner by hand and listed in docs/branch-protection.md; label creation is not committed configuration. Verified by `gh label list` and by reading docs/branch-protection.md.
- 006/FR-023: satisfied by docs/qa-pipeline.md, docs/branch-protection.md, CLAUDE.md, .github/PULL_REQUEST_TEMPLATE.md and the roadmap's Done entry; documentation prose is never asserted by a test (owner rule, CLAUDE.md), and that covers the template's rule that every example stays indented inside its comment and is never a column-1 keyed line — no test reads the template; the gate itself rejects a column-1 `Spec-PR: none` or `Spec-PR-reason:` example on the first web-form pull request that changes `src/` or `ui/`, but a column-1 `spec-change:` example would silently satisfy FR-010 and a column-1 `Spec-PR: #<n>` example is tolerated on a numbered pull request, so the owner's review of any template edit is the only check that those two stay indented. Verified by reading them.
- 006/SC-010: observed on the throwaway draft PR of quickstart scenario 6 — a label added or a description edited after opening produces a fresh check result on the same commit, and a manual re-run judges the current state (steps 2–4).
