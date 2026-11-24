---

description: "Task list for feature 006: human-approved spec workflow"
---

# Tasks: Human-Approved Spec Workflow

**Input**: Design documents in `/specs/006-human-approved-spec/` (plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md)

**Tests**: included and written first (Constitution Principle VII; FR-014, SC-002/003/006/007). The Python checker logic is unit-tested; the GitHub pipeline and branch protection are validated by the manual quickstart (no automated HS-code e2e applies — plan.md Complexity Tracking, accepted via analyze C1).

**Organization**: by user story. This feature adds **no `src/` code** — it lives in `.github/`, `scripts/`, `tests/unit/`, and `docs/`, extending feature 005's four-gate `qa.yml`. The spec-mode checker (User Story 2) sits in Foundational because User Story 1's spec-only path depends on it (analysis finding F1), so US1 is independently completable.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: can run in parallel (different file, no dependency on an unfinished task)
- **[Story]**: US1–US5; Setup/Foundational/Polish carry no story label (except the Foundational spec-mode tasks, tagged `[US2]` for traceability since they deliver User Story 2)

## Path conventions

Single repo; CI and governance files at `.github/`, checker scripts at `scripts/`, unit tests at `tests/unit/`, docs at `docs/`.

---

## Phase 1: Setup

- [X] T001 Confirm the feature needs no new runtime/pip dependency (Principle X) and that `.github/workflows/qa.yml` (feature 005's four gates: traceability, quality, review, notify) is the baseline to extend; this feature changes only `.github/`, `scripts/`, `tests/unit/`, and `docs/`.

---

## Phase 2: Foundational (blocking prerequisites)

- [X] T002 Add a `classify` job to `.github/workflows/qa.yml`: compute changed files with `git diff --name-only origin/${{ github.base_ref }}...HEAD`, set output `spec_only=true` when none start with `src/`, `tests/`, `ui/`, or `scripts/` (else `false`), and **always exit 0**; make `traceability`, `quality`, and `review` declare `needs: classify` so they always run and report (FR-002, FR-006).
- [X] T003 [P] [US2] Write `tests/unit/test_check_spec.py` (FR-003, SC-002, SC-006): a well-formed feature directory passes; a duplicate definition fails and names the ID; an orphan reference (referenced, never defined) fails and names the ID; a malformed ID (`FR-7`, `FR-0001`) fails; a clean minimal spec passes; a numbering gap does **not** fail.
- [X] T004 [US2] Implement `scripts/check_spec.py` (FR-003, FR-014): resolve the feature dir (CLI arg, else branch prefix like `check_traceability.py`), read every `*.md` under it, collect definitions (`- **FR-### / SC-###**`) and references (`(FR|SC)-\d+` tokens), fail (exit 1, naming each offender) on a malformed id (`^(FR|SC)-\d{3}$` fails), a duplicate definition, or an orphan reference; pass (exit 0) otherwise; gaps allowed. Makes T003 pass. **(Delivers User Story 2 — spec-mode validation — placed in Foundational because US1's spec-only traceability gate depends on it.)**

**Checkpoint**: every required job can read `needs.classify.outputs.spec_only`; none is ever skipped; and the spec-mode checker is correct and unit-tested, ready for US1's traceability wiring.

---

## Phase 3: User Story 1 — A human approves each spec before implementation (Priority: P1) 🎯 MVP

**Goal**: a spec-only PR takes the lightweight path (spec-mode traceability + spec review; quality reports success without its heavy work), and `master` requires a code-owner approval before merge.

**Independent Test**: open a PR changing only `specs/` and `docs/`; confirm the spec path runs (spec-mode check + spec review), quality is green without running its steps, and the merge is blocked until a code owner approves. (Self-contained: all dependencies are in Foundational.)

### Implementation

- [X] T005 [P] [US1] Create `.github/CODEOWNERS` assigning `*` and `/specs/` to the repository owner `@yorkzhangyong-bot` (FR-007).
- [X] T006 [P] [US1] Create `.github/review/spec-checklist.md` — the spec review standard: ambiguity, missing or weak success criteria, untestable requirements, and conflicts with the constitution; same `severe`/`major`/`minor`/`possible` grading and `VERDICT:` line as `checklist.md` (FR-004).
- [X] T007 [US1] In `.github/workflows/qa.yml`, guard the `quality` job's heavy steps with `if: needs.classify.outputs.spec_only != 'true'` so a spec-only PR's `quality` job **reports success without running its heavy steps** (lint, type check, tests, coverage, secret and dependency scans) (FR-005, FR-006).
- [X] T008 [US1] In `.github/workflows/qa.yml`, add a spec-only `review` step (gated on `spec_only == 'true'`) running `anthropics/claude-code-action@v1` against `.github/review/spec-checklist.md` + the feature spec, keeping the shared `VERDICT: FAIL` enforcement step (FR-004).
- [X] T009 [US1] In `.github/workflows/qa.yml`, branch the `traceability` job: run `python scripts/check_spec.py` when `spec_only == 'true'`, else the existing `check_traceability.py` (FR-003, FR-005). Depends on `scripts/check_spec.py` from Foundational T004.
- [X] T010 [P] [US1] Create `docs/branch-protection.md` — the exact manual GitHub settings for `master`: require a PR; require 1 approval; require review from Code Owners; require status checks `traceability`/`quality`/`review` with "branches up to date"; no bypass. Note the required-check names must match the `qa.yml` job names, protection is applied only after the workflow merges, and **SC-004's guarantee (no unapproved merge) holds only once the owner has applied these settings** (FR-008, FR-013).

**Checkpoint**: the spec-only path and the approval gate work end to end (approval itself is enforced once T010's settings are applied manually).

---

## Phase 4: User Story 3 — Implementation PRs cannot silently rewrite the approved spec (Priority: P2)

**Goal**: on an implementation PR, the traceability job also enforces the `Spec-PR: #<n>` reference and the `spec-change:` acknowledgment.

**Independent Test**: an implementation PR with no `Spec-PR:` line fails; adding it passes. A PR that edits a spec file alongside `src/` without `spec-change:` fails; adding it passes; a code-only PR needs neither extra note for the spec-change rule.

### Tests (write first, must fail)

- [X] T011 [P] [US3] Write `tests/unit/test_check_traceability.py` (FR-009, FR-010, FR-011, SC-003, SC-007) for the pure helpers: `is_spec_only(changed_files)`; the spec-change rule (required when changed files include both `specs/**` and `src/**`, satisfied by a `^spec-change:\s*\S` line, not required otherwise); `has_spec_pr_reference(pr_body)` (a `^Spec-PR:\s*#\d+` line) present/absent.

### Implementation

- [X] T012 [US3] Extend `scripts/check_traceability.py` (FR-009, FR-010, FR-011): add the pure helpers above; on an implementation PR, read changed files (`git diff` vs `$GITHUB_BASE_REF`) and the PR body (`$PR_BODY`, missing = empty) and fail (exit 1, with a clear message) when a required `spec-change:` note or the `Spec-PR: #<n>` line is missing — alongside the existing tests-traceability check. Makes T011 pass.
- [X] T013 [US3] In `.github/workflows/qa.yml`, pass `PR_BODY: ${{ github.event.pull_request.body }}` to the `traceability` job so `check_traceability.py` can read it on the implementation-PR path (FR-009, FR-010).

**Checkpoint**: implementation PRs are gated on the spec-PR reference and the spec-change acknowledgment.

---

## Phase 5: User Story 4 — Document the cycle and the reproducible protection (Priority: P3)

**Goal**: the README and `docs/qa-pipeline.md` describe the full cycle so a contributor can follow it and the owner can reproduce branch protection.

**Independent Test**: a reader can name each step of the cycle from the docs, and the owner can apply `docs/branch-protection.md` to get the required behaviour.

### Implementation

- [X] T014 [P] [US4] Update `docs/qa-pipeline.md` (FR-012): document the spec-only path (classify → spec-mode traceability, success-without-running quality, spec-checklist review), the implementation-PR rules (`Spec-PR:`, `spec-change:`), and link `docs/branch-protection.md`.
- [X] T015 [P] [US4] Update `README.md` (FR-012, SC-005): describe the cycle specify → clarify → spec PR → human approval → plan/tasks/implement → implementation PR → four gates → human merge, linking the QA-pipeline and branch-protection docs.

**Checkpoint**: the workflow is documented and reproducible from the repo alone.

---

## Phase 6: Polish & cross-cutting

- [X] T016 Run `uv run pytest tests/unit/test_check_spec.py tests/unit/test_check_traceability.py -q` and the full `uv run pytest`; fix any failure (SC-002, SC-003, SC-006, SC-007).
- [X] T017 [P] Run `uvx ruff check scripts tests` and fix lint on the new/changed scripts and tests.
- [X] T018 Dogfood: run `uv run python scripts/check_spec.py specs/006-human-approved-spec` and confirm exit 0 (this feature's own spec passes spec-mode).
- [X] T019 Confirm the spec review and spec-mode check read only `specs/`/`docs/` and leak no secret, and that the required-check names in `docs/branch-protection.md` match the `qa.yml` job names exactly (FR-006, FR-013).
- [X] T020 [P] Validate `.github/workflows/qa.yml` parses as YAML and the `classify` output is wired into `traceability`, `quality`, and `review`.

---

## Phase 7: User Story 5 — An honest Spec-PR path for refactor and bug-fix PRs (added 2026-11-24)

**Spec amendment of 2026-11-24**: FR-009 and SC-007 amended; FR-015–FR-024 and SC-008–SC-010 added (spec.md,
Clarifications Session 2026-11-24; plan.md "Change 2026-11-24"; research.md §9–§17; contracts/pr-rules.md).

**Goal**: the traceability job accepts `Spec-PR: none` only with exactly one reason line (`Spec-PR-reason: refactor`
or `Spec-PR-reason: bugfix: #<issue>`, whose number must be an existing issue of this repository) and the matching
label (`refactor` / `bugfix`, not the other), is re-evaluated when the body or a reason label changes — and only
then — names the accepted forms when it fails, and leaves the `Spec-PR: #<n>` form unchanged.

**Independent Test**: the unit matrix over the pure helpers (T021) is green; then, on a throwaway draft PR based on the
feature branch (quickstart scenario 6): with the label it passes, without it fails, a label change or a body edit
re-runs only the traceability job, a title edit re-runs nothing, a manual re-run judges the current state, and a
bugfix number that is not an issue here fails.

### Tests (write first, must fail)

- [X] T021 [US5] Extend `tests/unit/test_check_traceability.py` (006/FR-009, 006/FR-015, 006/FR-016, 006/FR-017, 006/FR-018, 006/FR-020, 006/FR-022, 006/FR-024, 006/SC-008, 006/SC-009) with the matrix of contracts/pr-rules.md (its Tests section is the row list) over the pure `spec_pr_rule_problems(pr_body, labels, issue_exists)` (a stubbed lookup; `lambda n: True` wherever a bugfix row is meant to pass), `parse_pr_state(raw)`, `parse_issue_lookup(raw, repository, number)` and `pr_rule_problems(files, pr_body, labels, issue_exists)`, plus `pr_state()` and `issue_exists_in_repo()` with the environment and `subprocess.run` monkeypatched. **Pass**: `#<n>` with neither new line — with no labels, with `refactor`, with both labels, beside a second number, beside `Spec-PR: TBD`, when the numbered line sits inside a multi-line `<!--` … `-->` block whose keyed line starts in column 1 (the raw description counts), and beside a one-line reason comment `<!-- Spec-PR-reason: refactor -->` (not a keyed line, so no conflict); `none` + `refactor` + label `refactor`, also when both lines sit inside a multi-line `<!--` … `-->` block whose keyed lines start in column 1; `none` + `bugfix: #12` + label `bugfix` with the lookup stub answering `True` (`#999999`, `bugfix:#12` and `bugfix:<tab>#12` too — the form is the rule's business, existence the stub's); case variants (`spec-pr: NONE`, `SPEC-PR-REASON: Refactor`, label `Refactor`); CRLF line endings. **Fail** (each message names the three accepted forms and the failed condition; the row 2, 4 and 6 messages also carry the hint that every column-1 keyed line counts, also inside code blocks and HTML comments, so quoted examples must be indented; echoed values appear as `repr` literals): no `Spec-PR:` line; `Spec-PR: TBD` alone; `Spec-PR:` with an empty value; `none` alone; `none` + a reason + no labels; `none` + `refactor` + label `bugfix` only; `none` + `refactor` + both labels; `none` + `bugfix: #12` + label `refactor`; malformed reasons `refactoring`, `bugfix`, `bugfix: 12`, `bugfix: #`, `refactor of the graph`, `bugfix: #١٢` (non-ASCII digits); `none because …` alone; `none` + `none because …`; `none` + `TBD`; two `none` lines; two reason lines (same and different); `#<n>` + `none`; `#<n>` + `none because …`; `#<n>` + a reason line, also when that reason line sits inside a multi-line `<!--` … `-->` block with the reason line in column 1 (raw read: a conflict); a reason line with no `Spec-PR:` line; an indented or bulleted `Spec-PR: none`; a one-line comment `<!-- Spec-PR: #12 -->` and a one-line honest-path pair `<!-- Spec-PR: none -->` + `<!-- Spec-PR-reason: refactor -->` (not keyed lines: the key is not in column 1); a `none` value carrying a lone carriage return and `::warning::` (message shows the escaped literal, no raw CR). **Parse**: `parse_pr_state` on valid JSON → body and label names; `body` missing or non-string → `""`; `labels` with an element lacking a string `name`, or not a list → `[]`; `None`, `""`, invalid JSON, a non-object → `("", [])`. **Live read, failure path** (`pr_state` with `os.environ` and `subprocess.run` monkeypatched, stdout captured): no `PR_NUMBER` → `("", [])` and `subprocess.run` is never called; a non-zero `gh` exit → `("", [])`; `subprocess.TimeoutExpired` → `("", [])`; `FileNotFoundError` (no `gh` on the path) → `("", [])`; a successful call → `parse_pr_state` of its stdout; and the notice printed on every failure carries no body or label value. **Issue lookup** (FR-024): with a stub that records its calls — `none` + `bugfix: #37` + label `bugfix` and a stub returning `True` → `[]` with exactly one call; the same with a stub returning `False` → exactly the row-10 message naming `37` and ending with the accepted forms; the refactor path, and every bugfix body that fails rows 1–9 (no label, both labels, malformed number) → zero calls; `parse_issue_lookup` → `True` for an issue object of this repository (`number` matching, no `pull_request` key, `repository_url` ending with `/repos/<repository>` in any letter case, `state` open or closed); `False` for a `pull_request` key, a `repository_url` of another repository (a transfer), a `number` that differs, a non-object, invalid JSON, `None`, `""`; `issue_exists_in_repo` with `subprocess.run` monkeypatched → `False` on a non-zero exit, `TimeoutExpired`, `FileNotFoundError`, and `parse_issue_lookup` of the stdout on success; every failure notice names only the digits. **Wiring**: `pr_rule_problems` (with `issue_exists` passed through) — a `src/` change + a valid honest path + `["refactor"]` → `[]`; the same with `[]` labels → exactly the label failure; a tests-only change with a lone `Spec-PR: none` → `[]`; a `src/` + `specs/` honest path without `spec-change:` → exactly the spec-change problem; the same with a column-1 `spec-change:` line, outside a comment or inside a multi-line `<!--` … `-->` block (the raw description counts) → `[]`; the same with only a one-line `<!-- spec-change: x -->` → the spec-change problem (not a keyed line). Leave every existing assertion untouched.
- [ ] T034 [US5] Write `tests/unit/test_qa_recheck.py` (006/FR-019) for `scripts/qa_recheck.py`'s step machine (`next_action`, `run_status` additionally `"error"` and `"no_job"`) and `already_fresh`, against a stub, injected API client (no network, no `gh`) — contracts/pr-rules.md "Recheck script" is the row list: waiting (poll again); `completed` with no re-run requested yet (request it); refused, re-read shows the run still running (retry); refused, re-read shows the run `completed` (the comment, exit 1); the budget exhausted while waiting or retrying (the comment, exit 1, reason `timeout`); no run for the head SHA (a successful empty list), and a run in `action_required` / `waiting` (exit 0, no comment); `already_fresh` true (skip the POST, exit 0, no comment, no re-run spent). **Failure-handling rows (review round 3)**: `get_latest_run` raises → retried, never read as "no run"; the budget then exhausted while it keeps failing → the comment, exit 1, reason `error`, not exit 0; a poll (`get_run`) error during step 2 → retried, the comment when the budget runs out; a job-lookup (`get_job`) error → retried like any other step-3 failure; `get_job` succeeding with no job named `traceability` → the comment at once, no retry spent; a `get_recheck_run_created_at` error → retried, the POST still sent once it succeeds, never skipped; `already_fresh` given a missing or unparsable timestamp → `False` (not an exception), so the POST is sent; an uncaught exception anywhere in the sequence → the script's entry-point catch-all still posts the comment (with its one retry) before exit 1; the comment text itself (names only the reason class — `timeout`, `refused` or `error` — no body or label value, never contains `VERDICT: PASS` or `VERDICT: FAIL`). T033 makes this pass (as T022 does for T021).

### Implementation

- [X] T022 [US5] In `scripts/check_traceability.py` (FR-009, FR-015, FR-016, FR-017, FR-018, FR-020, FR-022, FR-024): add the patterns and helpers of contracts/pr-rules.md — `SPEC_PR_LINE_RE`, `REASON_LINE_RE`, `REASON_VALUE_RE` (`[0-9]+`), `REASON_LABELS`, `spec_pr_rule_problems(pr_body, labels, issue_exists)` (the eleven-row order over the raw description, as today; row 10 is the one injected lookup on the bugfix path; echoed values as `repr` truncated to 80 characters), `parse_pr_state`, the `gh pr view` subprocess `pr_state()` (reads `PR_NUMBER` from the environment and calls `subprocess.run` with a 30 s timeout; any failure → `("", [])` and a notice without values), `parse_issue_lookup(raw, repository, number)` and the `gh api repos/$GITHUB_REPOSITORY/issues/<n>` subprocess `issue_exists_in_repo(number)` (FR-024; any failure → `False` and a notice naming only the digits), and the pure wiring `pr_rule_problems(files, pr_body, labels, issue_exists)` with `_pr_rule_problems()` reduced to `pr_rule_problems(changed_files(), *pr_state(), issue_exists_in_repo)`; `PR_BODY` is no longer read; `changes_app_code` and the existing patterns stay unchanged; update the module docstring. Makes T021 pass.
- [X] T023 [US5] In `.github/workflows/qa.yml` (FR-018, FR-019, FR-024): keep the default pull-request events (no `types` list); on the traceability step replace `PR_BODY` by `PR_NUMBER: ${{ github.event.pull_request.number }}` and `GH_TOKEN: ${{ github.token }}`, and give the traceability job `permissions: {contents: read, pull-requests: read, issues: read}` (least privilege for the token that step exposes; the workflow-level `pull-requests: write` stays because `classify`, `quality` — the gitleaks action comments on PRs — and `notify` inherit it, while the review job declares its own permissions block). No job becomes conditional on the event, the review job included (research §11). (A workflow edit — the implementation PR merges by one of the two routes in docs/branch-protection.md.)
- [ ] T033 [P] [US5] Create `.github/workflows/qa-recheck.yml` and its script `scripts/qa_recheck.py` (FR-019) per contracts/pr-rules.md "Recheck workflow" and "Recheck script": `on.pull_request` with `types: [edited, labeled, unlabeled]` and `branches: [master]`; `permissions: {actions: write, contents: read, pull-requests: write}`; **no** `concurrency` group; one job with `timeout-minutes: 35` and the job-level `if` — `edited` with `github.event.changes.body` present, or `labeled`/`unlabeled` with `github.event.label.name` equal to `refactor` or `bugfix` — that runs `actions/checkout`, then `actions/setup-python` (as the traceability job does before `check_traceability.py`), then `python scripts/qa_recheck.py` with `GH_TOKEN: ${{ github.token }}`. The script implements steps 1–5 with one 30-minute budget and an injected API client whose every method returns a value or raises `RecheckApiError` after its own per-call timeout — never a silent `None`/empty for a failure: find the newest `qa.yml` run for `github.event.pull_request.head.sha` (a **successful** empty list, or a run in `action_required` / `waiting` → a notice, exit 0; a raised error → retried at the next poll, never read as "no run"); wait until its `status` is `completed` (poll every 30 s; an error retried the same way); find its job named `traceability` (an error retried the same way; a **successful** read that finds none goes straight to the failure signal — nothing to retry toward); before requesting a re-run, skip it and exit 0 when that job's latest attempt already started after this recheck run's own `created_at` (`already_fresh`, read via `GET /repos/{repo}/actions/runs/{github.run_id}`; an error reading `created_at` is retried, never treated as fresh; `already_fresh` itself never raises — a missing or unparsable timestamp makes it return `False`, so the POST is sent, never skipped); otherwise `POST /repos/{repo}/actions/jobs/{job_id}/rerun` (accepted → exit 0; refused, for any reason — the endpoint documents only `201`/`403`, and GitHub sends the same `403` whether another attempt is in progress or the refusal is final — re-read the run: not `completed` → back to waiting and retry within the budget; still `completed` → the failure signal; a re-read error retried the same way; the budget exhausted while waiting, erroring or retrying → the failure signal). Failure signal: one fixed-text PR comment naming only the reason class (`timeout`, `refused` or `error`), no body or label value, never containing `VERDICT: PASS`/`VERDICT: FAIL`, saying the traceability result may be stale and to refresh it by a push or a manual re-run of the `traceability` job, retried once on failure, then exit 1; on a fork the comment is refused too → notice, exit 1; the script's entry point catches any other exception and still attempts the comment before exit 1. No step reads or prints the body; every API call carries its own timeout (e.g. 30 s). Makes T034 pass. (A workflow file — the implementation PR merges by one of the two routes in docs/branch-protection.md.)
- [ ] T024 [US5] Owner, by hand (FR-021): create the labels `refactor` (a behaviour-preserving change that implements no spec; pairs with `Spec-PR: none` + `Spec-PR-reason: refactor`) and `bugfix` (a fix for behaviour an approved spec already covers; pairs with `Spec-PR: none` + `Spec-PR-reason: bugfix: #<issue>`) with `gh label create <name> --description "…" --color <hex>`; the exact commands are recorded by T025.
- [ ] T025 [P] [US5] Update `docs/branch-protection.md` (FR-021): a "Labels" section listing the two labels, their meaning, the create commands, and that the traceability gate reads them (names compared ignoring case).
- [ ] T026 [P] [US5] Update `docs/qa-pipeline.md` (FR-023): the traceability row and the implementation-PR rules — the three accepted forms, the fail-closed cases, the issue lookup, the recheck (a body change or a `refactor`/`bugfix` label change re-runs only the traceability job; a title edit or another label re-runs nothing), the owner's merge rule — after a failed recheck (its stale-result comment), do not merge until a traceability attempt that started after that comment has passed (a push, a manual re-run, or a later automatic recheck re-run); on a pull request from a fork, which gets no comment, refresh traceability with a push or a manual re-run after the last body or label change before merging, whatever the recheck shows — the rollout note (a PR open across the merge needs one push), and that a tests-only or scripts-only PR needs no `Spec-PR:` line.
- [ ] T027 [P] [US5] Update `CLAUDE.md` (FR-023): the "Spec Kit flow" and "Git / review" lines on the Spec-PR rule (the accepted forms and the labels; workflow-editing PRs still admin-merged), plus a dated learned note.
- [ ] T028 [P] [US5] Update `docs/roadmap.md` (FR-023): move the Housekeeping item "Traceability gate: an honest path for refactor and bug-fix PRs" to Done inside the implementation PR, naming the spec PR and the implementation PR.
- [ ] T032 [P] [US5] Update `.github/PULL_REQUEST_TEMPLATE.md` (FR-023): inside its HTML comment, replace the stale "Implementation PRs must reference the merged spec PR" text by the rule as enforced — a PR that changes `src/` or `ui/` carries `Spec-PR: #<n>`, or `Spec-PR: none` + `Spec-PR-reason: refactor` + the `refactor` label, or `Spec-PR: none` + `Spec-PR-reason: bugfix: #<issue>` + the `bugfix` label — with every example indented four spaces inside the comment — the gate reads the raw description, so a template example must never be a column-1 keyed line, comment or not — and a note that a keyed line counts only in column 1; keep the `spec-change:` and spec-only notes. The `spec-change:` example is the one with no backstop — a column-1 copy would silently satisfy FR-010 on every web-form PR that edits `specs/` beside `src/` — so the owner's review of any template edit must keep it indented. No test asserts the template's text (owner rule); justified in traceability.md.
- [ ] T029 [US5] Run `uv run pytest tests/unit/test_check_traceability.py -q`, the full offline suite (`uv run pytest tests/unit tests/integration`), `uvx ruff check scripts tests`, and `GITHUB_HEAD_REF=006-gate-honest-path uv run python scripts/check_traceability.py` (no `GITHUB_BASE_REF`, so only tests-traceability runs) to confirm every 006 id is traced by a test or by `traceability.md` (SC-008, SC-009).
- [ ] T030 [P] [US5] Validate `.github/workflows/qa.yml` parses, keeps the default pull-request events, passes `PR_NUMBER` and `GH_TOKEN` to the traceability step and grants that job `issues: read`; validate `.github/workflows/qa-recheck.yml` parses, lists exactly `edited`, `labeled`, `unlabeled` on `master`, holds `actions: write`, `contents: read` and `pull-requests: write` only, carries the relevance `if`, `timeout-minutes: 35` and **no** `concurrency` block, and that its job runs `actions/checkout`, then `actions/setup-python`, then `python scripts/qa_recheck.py`; confirm by reading that `docs/branch-protection.md` names the labels exactly as the gate compares them (FR-019, FR-021).
- [ ] T031 [US5] Before the implementation PR merges, once T022/T023 are pushed on the feature branch and the labels exist (T024): run quickstart scenario 6 on a throwaway **draft** PR to `master` from a scratch branch based on the feature branch (no numeric prefix, e.g. `probe/honest-path`; mergeable, since GitHub runs no `pull_request` workflow on a conflicting PR) that first restores `specs/` to master's version (`git checkout --no-overlay origin/master -- specs/` — an overlay checkout keeps files the branch added under `specs/` — committed together with the `src/` comment, after which `git diff --name-only origin/master...HEAD -- specs/` must print nothing) and adds one trivial `src/` change — a `pull_request` run uses the PR's own merged workflow file, so the draft runs the new gate; use the numbers scenario 6 names (`#37`, a closed issue of this repository — it leaves a cross-reference there; `#999999`, non-existent; `#49`, a pull request); cover steps 1–8 (the `labeled` event's recheck re-runs only the traceability job of the `opened` run; removing the label re-runs it and fails with a message naming the accepted forms; swapping `refactor` for an unrelated label in one action turns `traceability` red (the irrelevant event cancels nothing); swapping `refactor` for `bugfix` in one action overlaps two *relevant* rechecks on the same run — a re-run request may be refused; either way both exit 0, no stale-result comment, and `traceability` still turns red (the re-read path itself is T034's to prove); a manual re-run judges the current state; `#37` passes, `#999999` and `#49` fail as not an issue of this repository; a title edit and an unrelated label re-run nothing; the numbered form ignores labels; a spec edit without `spec-change:` fails), then close the draft unmerged and delete the branch (FR-018, FR-019, FR-020, FR-024, SC-009, SC-010).

**Checkpoint**: a refactor or bug-fix PR passes the gate truthfully; everything else still fails closed.

---

## Dependencies & execution order

- **Setup (T001)** → **Foundational (T002–T004)** blocks everything. Foundational now delivers both the `classify` output (drives the spec-only and implementation-PR paths) and the spec-mode checker `check_spec.py` (consumed by US1's traceability wiring).
- **US1 (P1)** is the MVP and is now **self-contained**: its only external dependency (`check_spec.py`, used by T009) is satisfied in Foundational (T004). The rest of US1 (T005, T006, T007, T008, T010) depends only on Foundational.
- **US3 (P2)** depends only on Foundational; independent of US1.
- **US4 (P3)** documents the finished pipeline; depends on US1/US3 being settled.
- **qa.yml is one file**: T002, T007, T008, T009, T013 touch it and are **sequential** with each other (not `[P]`).
- Within a story / phase: tests before implementation (T003 before T004; T011 before T012).
- **Phase 7 (US5, added 2026-11-24)** depends on nothing unfinished: T021 before T022 (tests first); T034 before
  T033, the same way — T033 makes T034 pass, as T022 makes T021 pass; T023 and T033 (two workflow files) are
  independent of T022 but all three are needed end to end; T024 (labels, by the owner) before
  T031; T025–T028 and T032 (docs, template) any time after the rule is settled; T029 and T030 after
  T022/T023/T033/T034; T031 (the throwaway draft PR) after T022/T023 are pushed and the labels exist — before the
  implementation PR merges, not after.

## Parallel opportunities

- Foundational: T003 (test file) ‖ T002 (qa.yml) — different files; T004 follows T003 (tests-first).
- US1: T005 ‖ T006 ‖ T010 (three different new files). The qa.yml edits (T007, T008, T009) are sequential.
- Tests across phases: T003 ‖ T011 (different test files).
- US4 docs: T014 ‖ T015.
- Polish: T017 ‖ T020.
- Phase 7: T021 ‖ T034 (different test files); T025 ‖ T026 ‖ T027 ‖ T028 ‖ T032 (docs and template); T022 ‖ T023 ‖ T033 (script vs the two workflow files, each making its own tests pass); T029 ‖ T030.

## Implementation strategy

1. Setup + Foundational (classify **and** `check_spec.py` + its tests).
2. **US1 (MVP)** — the spec-only path + CODEOWNERS + branch-protection guide → the approval gate works, standing alone on Foundational.
3. US3 — implementation-PR rules; US4 — docs.
4. Polish: full suite, ruff, dogfood, name-match audit, YAML validation. Apply `docs/branch-protection.md` manually (one-time, by the owner) — SC-004 holds only after this.
5. *(2026-11-24)* Phase 7 — the honest Spec-PR path: tests, script, workflow, labels, docs and template; verify live
   on a throwaway draft PR based on the feature branch (T031) before the implementation PR merges by one of the two
   workflow-edit routes.

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

### Added 2026-11-24 (Phase 7)

| FR | Tasks | | SC | Tasks |
|---|---|---|---|---|
| FR-009 (amended) | T021, T022 | | SC-007 (amended) | T021, T022 |
| FR-015 | T021, T022 | | SC-008 | T021, T022, T029, T031 |
| FR-016 | T021, T022 | | SC-009 | T021, T022, T029, T031 |
| FR-017 | T021, T022 | | SC-010 | T034, T033, T031 |
| FR-018 | T021, T022, T023, T031 | | | |
| FR-019 | T023, T034, T033, T030, T031 | | | |
| FR-020 | T021, T022, T031 | | | |
| FR-021 | T024, T025, T030 | | | |
| FR-022 | T021, T022 | | | |
| FR-023 | T026, T027, T028, T032 | | | |
| FR-024 | T021, T022, T023, T031 | | | |
