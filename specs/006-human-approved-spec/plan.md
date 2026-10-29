# Implementation Plan: Human-Approved Spec Workflow

**Branch**: `006-human-approved-spec` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/006-human-approved-spec/spec.md`

## Summary

No feature implementation reaches `master` until a human has approved its specification on GitHub. The author
ships the Spec Kit artifacts as a **spec-only pull request** (no `src/`/`tests/`/`ui/`/`scripts/` changes); the
QA pipeline takes a lightweight path for it (spec-mode requirement check + a spec-focused Claude review, skipping
the quality gate and the tests-traceability check); a code owner approves and merges; only then does an
**implementation PR** proceed through the full four gates. Implementation PRs must carry a `Spec-PR: #<n>`
reference and must acknowledge any spec edit with a `spec-change:` line. The enforcement combines a new pure
checker (`scripts/check_spec.py`), additions to the existing traceability checker, branches inside the existing
`qa.yml` jobs, a `CODEOWNERS` file, and a manual branch-protection guide (GitHub cannot set its own protection).

## Technical Context

**Language/Version**: Python 3.12 (checker scripts), GitHub Actions workflow YAML, Markdown (docs, CODEOWNERS).

**Primary Dependencies**: GitHub Actions; the Claude Code Action (`anthropics/claude-code-action@v1`, already used by gate 4); the `gh` CLI and `git` (already available on runners). `check_spec.py` uses the Python standard library only (`re`, `pathlib`, `sys`). No new runtime or pip dependency (Principle X).

**Storage**: N/A — CI configuration, checker scripts, and docs; no database, no persisted state.

**Testing**: pytest unit tests for `check_spec.py` and for the pure helpers added to `check_traceability.py` (classification, spec-change rule, spec-PR reference). End-to-end validation of the GitHub flow is manual (quickstart), as it depends on GitHub PR events and branch protection that cannot run inside pytest.

**Target Platform**: GitHub (Actions `ubuntu-latest` runners + repository branch-protection settings).

**Project Type**: CI / repository-governance tooling in a single repo; no application (`src/`) changes.

**Performance Goals**: a spec-only PR completes its checks without the quality gate's heavy work (lint, type, tests, coverage, scans), so the spec path finishes in well under a minute on the runner.

**Constraints**: branch protection and `CODEOWNERS` enforcement are GitHub platform settings applied manually (they cannot be committed from the repo); every required status check (`traceability`, `quality`, `review`) MUST report a result on every PR — reporting success when it is skipped — so protection is never left waiting (FR-006); no new runtime dependency (Principle X).

**Scale/Scope**: small — one modified workflow, one new checker + one extended checker, two new docs, one modified doc, `CODEOWNERS`, a new spec-review checklist, and their unit tests. Governs this repository's PR flow from feature 006 onward.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Security, not quality** — N/A to behaviour; this is a process gate. It does not add quality metrics to the product and does not block adding them later. **Pass.**
- **II / III / V / VI** (hard evidence, attacker model, learn-from-every-run, OWASP findings) — N/A; this feature does not touch the attack, judge, experience-store, or report paths. **Pass.**
- **IV. Secrets never leave the vault** — the spec-mode check and the spec review operate over `specs/` and `docs/`, which hold no credentials; the review reuses the existing `ANTHROPIC_API_KEY` and introduces no new secret or new secret exposure. **Pass.**
- **VII. Tests first, thin slices** — `check_spec.py` and the new traceability helpers are built test-first with unit tests (duplicate/orphan/well-formed IDs; spec-only classification; spec-change and spec-PR-reference rules). The "one end-to-end test against the HS-code target" does not apply — this feature has no target interaction and its real end-to-end path is a GitHub PR event; that path is validated by the manual scenarios in `quickstart.md`. Justified deviation, recorded below.
- **VIII. Only attack what you own; bounded harm** — N/A. **Pass.**
- **IX. Simple enough for a vibe coder** — the governance cycle is developer-facing; the end-user's paste-a-URL-read-a-report flow is unchanged. **Pass.**
- **X. Fixed stack; new deps justified** — no new dependency; `check_spec.py` is standard-library Python, the review action and `gh`/`git` are already present. **Pass.**

**Result: PASS** (one justified deviation on the Principle VII HS-code e2e — see Complexity Tracking).

## Project Structure

### Documentation (this feature)

```text
specs/006-human-approved-spec/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── check-spec.md        # spec-mode checker CLI
│   ├── pr-rules.md          # classification + spec-change + spec-PR-reference rules
│   └── governance.md        # workflow jobs, required checks, CODEOWNERS, branch protection
└── tasks.md             # /speckit-tasks output (not created here)
```

### Source Code (repository root)

```text
.github/
├── workflows/qa.yml          # MODIFIED: add a classify step/job; branch traceability, quality, review on spec-only
├── CODEOWNERS                # NEW: /specs/ (and the repo) owned by the repository owner
└── review/
    ├── checklist.md          # existing (code review standard)
    └── spec-checklist.md     # NEW: spec review standard (ambiguity, missing SC, untestable reqs, constitution conflicts)

scripts/
├── check_spec.py             # NEW: spec-mode requirement check over a feature directory (FR-003, FR-014)
└── check_traceability.py     # MODIFIED: on implementation PRs also apply the spec-change (FR-010/11) and
                              #           spec-PR-reference (FR-009) rules; expose pure helpers for unit tests

tests/unit/
├── test_check_spec.py        # NEW: well-formed / duplicate / orphan / clean-spec (SC-002, SC-006)
└── test_check_traceability.py# NEW: classification + spec-change + spec-PR-reference helpers (SC-003, SC-007)

docs/
├── qa-pipeline.md            # MODIFIED: document the spec-only path and the implementation-PR rules
└── branch-protection.md      # NEW: exact manual GitHub settings (FR-013)

README.md                     # MODIFIED: document the full cycle (FR-012)
```

**Structure Decision**: Single repository, extending feature 005's QA pipeline rather than replacing it. This
feature adds **no `src/` code** — it lives in `.github/`, `scripts/`, `tests/unit/`, and `docs/`. The pure
validation logic goes in Python checkers under `scripts/` (unit-testable, no I/O beyond reading files and env);
the GitHub-specific wiring (classification from the PR diff, reading the PR body, choosing the review checklist,
reporting a skipped gate as success) lives in `qa.yml`; the parts GitHub will not let a repo set itself
(branch protection) are a manual guide.

### Key design decisions (detail in research.md)

- **Required checks always run and report (FR-006).** `traceability`, `quality`, and `review` run on every PR. A
  fast `classify` job computes `spec_only` (true when the PR changes nothing under `src/`, `tests/`, `ui/`,
  `scripts/`) and is written to always succeed, so the three required jobs never skip and never leave branch
  protection waiting. On a spec-only PR the quality job reports success without doing its heavy work.
- **Two checkers, clear split.** `check_spec.py` is pure and runs on spec-only PRs (validate the feature
  directory's `FR-###`/`SC-###`: well-formed, unique, no orphan references). `check_traceability.py` runs on
  implementation PRs (the existing tests-traceability plus the spec-change and spec-PR-reference rules, which read
  the changed paths and the PR body). Pure helpers are factored out of both for unit testing.
- **Review checklist switch.** The `review` job runs the Claude Code Action against `spec-checklist.md` on
  spec-only PRs and against `checklist.md` otherwise; the existing verdict-enforcement step (`VERDICT: FAIL` →
  fail) is shared.
- **Human approval is platform-enforced.** `CODEOWNERS` assigns `specs/` to the owner; branch protection
  (manual) requires a PR, a code-owner approval, and the three required checks. Documented in
  `branch-protection.md` because it cannot be committed.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| No automated HS-code e2e (Principle VII) | The feature's end-to-end path is a GitHub PR event (spec PR → approval → impl PR → gates), which cannot be exercised from pytest and does not touch the sacrificial target. | A pytest e2e against HS-code would test nothing about this feature; the real flow is validated by the manual scenarios in `quickstart.md`, and all pure logic has unit tests. |

Accepted via `/speckit-analyze` (finding C1, 2026-10-29), mirroring the feature 005 C3 resolution where the Principle VII end-to-end requirement was likewise settled by an explicit user decision.
