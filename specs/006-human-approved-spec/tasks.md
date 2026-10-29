---

description: "Task list for feature 006: human-approved spec workflow"
---

# Tasks: Human-Approved Spec Workflow

**Input**: Design documents in `/specs/006-human-approved-spec/` (plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md)

**Tests**: included and written first (Constitution Principle VII; FR-014, SC-002/003/006/007). The Python checker logic is unit-tested; the GitHub pipeline and branch protection are validated by the manual quickstart (no automated HS-code e2e applies — plan.md Complexity Tracking, accepted via analyze C1).

**Organization**: by user story. This feature adds **no `src/` code** — it lives in `.github/`, `scripts/`, `tests/unit/`, and `docs/`, extending feature 005's four-gate `qa.yml`. The spec-mode checker (User Story 2) sits in Foundational because User Story 1's spec-only path depends on it (analysis finding F1), so US1 is independently completable.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: can run in parallel (different file, no dependency on an unfinished task)
- **[Story]**: US1–US4; Setup/Foundational/Polish carry no story label (except the Foundational spec-mode tasks, tagged `[US2]` for traceability since they deliver User Story 2)

## Path conventions

Single repo; CI and governance files at `.github/`, checker scripts at `scripts/`, unit tests at `tests/unit/`, docs at `docs/`.

---

## Phase 1: Setup

- [ ] T001 Confirm the feature needs no new runtime/pip dependency (Principle X) and that `.github/workflows/qa.yml` (feature 005's four gates: traceability, quality, review, notify) is the baseline to extend; this feature changes only `.github/`, `scripts/`, `tests/unit/`, and `docs/`.

---

## Phase 2: Foundational (blocking prerequisites)

- [ ] T002 Add a `classify` job to `.github/workflows/qa.yml`: compute changed files with `git diff --name-only origin/${{ github.base_ref }}...HEAD`, set output `spec_only=true` when none start with `src/`, `tests/`, `ui/`, or `scripts/` (else `false`), and **always exit 0**; make `traceability`, `quality`, and `review` declare `needs: classify` so they always run and report (FR-002, FR-006).
- [ ] T003 [P] [US2] Write `tests/unit/test_check_spec.py` (FR-003, SC-002, SC-006): a well-formed feature directory passes; a duplicate definition fails and names the ID; an orphan reference (referenced, never defined) fails and names the ID; a malformed ID (`FR-7`, `FR-0001`) fails; a clean minimal spec passes; a numbering gap does **not** fail.
- [ ] T004 [US2] Implement `scripts/check_spec.py` (FR-003, FR-014): resolve the feature dir (CLI arg, else branch prefix like `check_traceability.py`), read every `*.md` under it, collect definitions (`- **FR-### / SC-###**`) and references (`(FR|SC)-\d+` tokens), fail (exit 1, naming each offender) on a malformed id (`^(FR|SC)-\d{3}$` fails), a duplicate definition, or an orphan reference; pass (exit 0) otherwise; gaps allowed. Makes T003 pass. **(Delivers User Story 2 — spec-mode validation — placed in Foundational because US1's spec-only traceability gate depends on it.)**

**Checkpoint**: every required job can read `needs.classify.outputs.spec_only`; none is ever skipped; and the spec-mode checker is correct and unit-tested, ready for US1's traceability wiring.

---

## Phase 3: User Story 1 — A human approves each spec before implementation (Priority: P1) 🎯 MVP

**Goal**: a spec-only PR takes the lightweight path (spec-mode traceability + spec review; quality reports success without its heavy work), and `master` requires a code-owner approval before merge.

**Independent Test**: open a PR changing only `specs/` and `docs/`; confirm the spec path runs (spec-mode check + spec review), quality is green without running its steps, and the merge is blocked until a code owner approves. (Self-contained: all dependencies are in Foundational.)

### Implementation

- [ ] T005 [P] [US1] Create `.github/CODEOWNERS` assigning `*` and `/specs/` to the repository owner `@yorkzhangyong-bot` (FR-007).
- [ ] T006 [P] [US1] Create `.github/review/spec-checklist.md` — the spec review standard: ambiguity, missing or weak success criteria, untestable requirements, and conflicts with the constitution; same `severe`/`major`/`minor`/`possible` grading and `VERDICT:` line as `checklist.md` (FR-004).
- [ ] T007 [US1] In `.github/workflows/qa.yml`, guard the `quality` job's heavy steps with `if: needs.classify.outputs.spec_only != 'true'` so a spec-only PR's `quality` job **reports success without running its heavy steps** (lint, type check, tests, coverage, secret and dependency scans) (FR-005, FR-006).
- [ ] T008 [US1] In `.github/workflows/qa.yml`, add a spec-only `review` step (gated on `spec_only == 'true'`) running `anthropics/claude-code-action@v1` against `.github/review/spec-checklist.md` + the feature spec, keeping the shared `VERDICT: FAIL` enforcement step (FR-004).
- [ ] T009 [US1] In `.github/workflows/qa.yml`, branch the `traceability` job: run `python scripts/check_spec.py` when `spec_only == 'true'`, else the existing `check_traceability.py` (FR-003, FR-005). Depends on `scripts/check_spec.py` from Foundational T004.
- [ ] T010 [P] [US1] Create `docs/branch-protection.md` — the exact manual GitHub settings for `master`: require a PR; require 1 approval; require review from Code Owners; require status checks `traceability`/`quality`/`review` with "branches up to date"; no bypass. Note the required-check names must match the `qa.yml` job names, protection is applied only after the workflow merges, and **SC-004's guarantee (no unapproved merge) holds only once the owner has applied these settings** (FR-008, FR-013).

**Checkpoint**: the spec-only path and the approval gate work end to end (approval itself is enforced once T010's settings are applied manually).

---

## Phase 4: User Story 3 — Implementation PRs cannot silently rewrite the approved spec (Priority: P2)

**Goal**: on an implementation PR, the traceability job also enforces the `Spec-PR: #<n>` reference and the `spec-change:` acknowledgment.

**Independent Test**: an implementation PR with no `Spec-PR:` line fails; adding it passes. A PR that edits a spec file alongside `src/` without `spec-change:` fails; adding it passes; a code-only PR needs neither extra note for the spec-change rule.

### Tests (write first, must fail)

- [ ] T011 [P] [US3] Write `tests/unit/test_check_traceability.py` (FR-009, FR-010, FR-011, SC-003, SC-007) for the pure helpers: `is_spec_only(changed_files)`; the spec-change rule (required when changed files include both `specs/**` and `src/**`, satisfied by a `^spec-change:\s*\S` line, not required otherwise); `has_spec_pr_reference(pr_body)` (a `^Spec-PR:\s*#\d+` line) present/absent.

### Implementation

- [ ] T012 [US3] Extend `scripts/check_traceability.py` (FR-009, FR-010, FR-011): add the pure helpers above; on an implementation PR, read changed files (`git diff` vs `$GITHUB_BASE_REF`) and the PR body (`$PR_BODY`, missing = empty) and fail (exit 1, with a clear message) when a required `spec-change:` note or the `Spec-PR: #<n>` line is missing — alongside the existing tests-traceability check. Makes T011 pass.
- [ ] T013 [US3] In `.github/workflows/qa.yml`, pass `PR_BODY: ${{ github.event.pull_request.body }}` to the `traceability` job so `check_traceability.py` can read it on the implementation-PR path (FR-009, FR-010).

**Checkpoint**: implementation PRs are gated on the spec-PR reference and the spec-change acknowledgment.

---

## Phase 5: User Story 4 — Document the cycle and the reproducible protection (Priority: P3)

**Goal**: the README and `docs/qa-pipeline.md` describe the full cycle so a contributor can follow it and the owner can reproduce branch protection.

**Independent Test**: a reader can name each step of the cycle from the docs, and the owner can apply `docs/branch-protection.md` to get the required behaviour.

### Implementation

- [ ] T014 [P] [US4] Update `docs/qa-pipeline.md` (FR-012): document the spec-only path (classify → spec-mode traceability, success-without-running quality, spec-checklist review), the implementation-PR rules (`Spec-PR:`, `spec-change:`), and link `docs/branch-protection.md`.
- [ ] T015 [P] [US4] Update `README.md` (FR-012, SC-005): describe the cycle specify → clarify → spec PR → human approval → plan/tasks/implement → implementation PR → four gates → human merge, linking the QA-pipeline and branch-protection docs.

**Checkpoint**: the workflow is documented and reproducible from the repo alone.

---

## Phase 6: Polish & cross-cutting

- [ ] T016 Run `uv run pytest tests/unit/test_check_spec.py tests/unit/test_check_traceability.py -q` and the full `uv run pytest`; fix any failure (SC-002, SC-003, SC-006, SC-007).
- [ ] T017 [P] Run `uvx ruff check scripts tests` and fix lint on the new/changed scripts and tests.
- [ ] T018 Dogfood: run `uv run python scripts/check_spec.py specs/006-human-approved-spec` and confirm exit 0 (this feature's own spec passes spec-mode).
- [ ] T019 Confirm the spec review and spec-mode check read only `specs/`/`docs/` and leak no secret, and that the required-check names in `docs/branch-protection.md` match the `qa.yml` job names exactly (FR-006, FR-013).
- [ ] T020 [P] Validate `.github/workflows/qa.yml` parses as YAML and the `classify` output is wired into `traceability`, `quality`, and `review`.

---

## Dependencies & execution order

- **Setup (T001)** → **Foundational (T002–T004)** blocks everything. Foundational now delivers both the `classify` output (drives the spec-only and implementation-PR paths) and the spec-mode checker `check_spec.py` (consumed by US1's traceability wiring).
- **US1 (P1)** is the MVP and is now **self-contained**: its only external dependency (`check_spec.py`, used by T009) is satisfied in Foundational (T004). The rest of US1 (T005, T006, T007, T008, T010) depends only on Foundational.
- **US3 (P2)** depends only on Foundational; independent of US1.
- **US4 (P3)** documents the finished pipeline; depends on US1/US3 being settled.
- **qa.yml is one file**: T002, T007, T008, T009, T013 touch it and are **sequential** with each other (not `[P]`).
- Within a story / phase: tests before implementation (T003 before T004; T011 before T012).

## Parallel opportunities

- Foundational: T003 (test file) ‖ T002 (qa.yml) — different files; T004 follows T003 (tests-first).
- US1: T005 ‖ T006 ‖ T010 (three different new files). The qa.yml edits (T007, T008, T009) are sequential.
- Tests across phases: T003 ‖ T011 (different test files).
- US4 docs: T014 ‖ T015.
- Polish: T017 ‖ T020.

## Implementation strategy

1. Setup + Foundational (classify **and** `check_spec.py` + its tests).
2. **US1 (MVP)** — the spec-only path + CODEOWNERS + branch-protection guide → the approval gate works, standing alone on Foundational.
3. US3 — implementation-PR rules; US4 — docs.
4. Polish: full suite, ruff, dogfood, name-match audit, YAML validation. Apply `docs/branch-protection.md` manually (one-time, by the owner) — SC-004 holds only after this.

## Requirement coverage

| FR | Tasks | | FR | Tasks |
|---|---|---|---|---|
| FR-001 | T014, T015 | | FR-008 | T010 |
| FR-002 | T002 | | FR-009 | T011, T012, T013 |
| FR-003 | T003, T004, T009 | | FR-010 | T011, T012, T013 |
| FR-004 | T006, T008 | | FR-011 | T011, T012 |
| FR-005 | T007, T009 | | FR-012 | T014, T015 |
| FR-006 | T002, T007 | | FR-013 | T010 |
| FR-007 | T005 | | FR-014 | T003, T004 |

| SC | Tasks | | SC | Tasks |
|---|---|---|---|---|
| SC-001 | T007, T009 | | SC-005 | T014, T015 |
| SC-002 | T003, T004 | | SC-006 | T003 |
| SC-003 | T011, T012 | | SC-007 | T011, T012 |
| SC-004 | T010 | | | |
