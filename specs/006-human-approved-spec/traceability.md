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
