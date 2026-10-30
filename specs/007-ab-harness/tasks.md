---
description: "Task list — feature 007 A/B Harness"
---

# Tasks: A/B Harness

**Input**: Design documents from `specs/007-ab-harness/` (plan.md, spec.md, research.md, data-model.md, contracts/)

**Branch**: `007-impl` — implementation PR carries **`Spec-PR: #4`** (feature-006 workflow).

**Tests**: included (Principle VII — tests-first). **Every test file is scoped for the feature-007 traceability gate**: a module-level `FEATURE = "007"` plus bare `FR-0xx`/`SC-0xx` citations, or `007/FR-0xx` tokens where id-shaped sample data would otherwise be miscounted. **No attack text** in any code, comment, test, or fixture — behaviour only (reuse the existing library).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US5, or Foundational / Polish

## Path conventions

Single project: `src/kestrel/…`, `ui/…`, `tests/{unit,integration,e2e}/…` at the repo root (per plan.md).

---

## Phase 1: Setup

- [X] T001 Create the `src/kestrel/experiments/` package: `__init__.py` and empty, docstring-only `engine.py`, `stats.py`, `pricing.py`, `results.py`; and a stub `src/kestrel/report/experiment.py`. Match the module roles in plan.md.
- [X] T002 [P] Confirm `ruff`/`pytest`/coverage already cover `src/kestrel/experiments/` and new `tests/**` (no config change expected; `src` is globbed). Record the 007 test-scoping convention (FEATURE marker / `007/FR-xxx`) at the top of each new test file as it is created.

---

## Phase 2: Foundational (BLOCKING — must complete before any user story)

**Purpose**: the shared primitives every story builds on. Write each test first and watch it fail.

- [X] T003 [P] [Foundational] Unit test `tests/unit/test_runs_single_turn_tokens.py` (cites `007/FR-006`): with a fake judge, `execute_run` on a canary **miss** sets `run.tokens_used == verdict.tokens`; a canary **hit** (judge not called) sets `tokens_used == 0`.
- [X] T004 [Foundational] Thread the judge's token count through single-turn runs in `src/kestrel/runs.py`: pass `tokens_used=verdict.tokens` in the judged-branch `_finish(...)`, and `tokens_used=0` on the canary-hit / no-judge / deadline / failed-send branches. No schema change. Make T003 pass; the existing single-turn run tests still pass. *(Prerequisite from research R3 — enables tokens/cost for single-turn arms.)*
- [X] T005 [P] [Foundational] Unit test `tests/unit/test_store_migration_v6.py` (cites `007/FR-016`): a seeded v5 database opens, gains `experiments` / `experiment_arms` / `experiment_runs`, and reports schema version 6 (mirror `test_store_migration_v5.py`).
- [X] T006 [Foundational] Add schema **v6** to `src/kestrel/store.py`: the three tables + indexes from data-model.md in `SCHEMA`, bump `SCHEMA_VERSION` to `"6"`, and add `"5"` to the accepted-upgrade set in `_migrate`. Make T005 pass.
- [X] T007 [P] [Foundational] Unit test `tests/unit/test_store_experiments.py` (cites `007/FR-003`, `007/FR-004`, `007/FR-016`): `create_experiment` + two arms; `add_experiment_run` links a run; status / `stopped_reason` transitions; progress counts; `uq_experiments_active` blocks a second running experiment per target.
- [X] T008 [Foundational] Implement experiment persistence on `TargetStore` in `src/kestrel/store.py`: `create_experiment`, `get_experiment`, `list_experiments`, `set_arm_order`, `add_experiment_run`, `set_experiment_status`, `experiment_progress`, `experiment_runs_for`. Make T007 pass. *(same file as T006 — sequential)*
- [X] T009 [P] [Foundational] Unit test `tests/unit/test_settings_prices.py` (cites `007/FR-006`, `007/FR-008`): `KESTREL_MODEL_PRICES="a=0.3,b=0.2"` parses to a mapping; experiment cap defaults load; a malformed price / non-positive cap raises `SettingsError`.
- [X] T010 [Foundational] Add `model_prices: Mapping[str, float]` and experiment cap defaults to `src/kestrel/settings.py` + `load_settings`: `max_runs=50`, `token_budget_total=500000`, `wall_clock_s=3600` (overridable per experiment, never unset). Make T009 pass.
- [X] T011 [P] [Foundational] Unit test `tests/unit/test_experiment_stats.py` (cites `007/FR-007`): `wilson_interval` against known values (1/10, 5/10, 0/20 → "no data"); `two_proportion` diff/z/p and `small_sample` flag (min n < 30, or expected count < 5).
- [X] T012 [P] [Foundational] Implement `src/kestrel/experiments/stats.py` (`wilson_interval`, `two_proportion`) with stdlib `math` only. Make T011 pass.
- [X] T013 [P] [Foundational] Unit test `tests/unit/test_experiment_pricing.py` (cites `007/FR-006`): `arm_cost(tokens, price_model, prices)` = tokens/1000 × price; `None` when the price_model has no configured price.
- [X] T014 [P] [Foundational] Implement `src/kestrel/experiments/pricing.py` (`arm_cost`, primary-model keyed). Make T013 pass.

**Checkpoint**: primitives ready — stories can begin.

---

## Phase 3: User Story 1 — Run a two-arm experiment and read the comparison (P1) 🎯 MVP

**Goal**: define a campaign + two differing arms, start the experiment, and get a side-by-side result.

**Independent test**: create two arms differing in one field → `201`; poll status to finished; `GET result` shows arm A and arm B with the diff and the difference in outcomes. Identical arms are rejected.

### Tests (write first)

- [X] T015 [P] [US1] Unit test `tests/unit/test_experiment_results.py` (cites `007/FR-006`, `007/FR-007`): `arm_result` splits confirmed vs suspected, computes mean turns / mean tokens / cost and per-family / per-OWASP counts; `build_comparison` reports the per-metric diff and the significance block on the confirmed rate.
- [X] T016 [P] [US1] Unit test `tests/unit/test_experiment_engine.py` (cites `007/FR-003`, `007/FR-004`, `007/FR-015`): with fakes (sender/judge/attacker, temp store, stub experience), `run_experiment` runs arm A then arm B, records one `experiment_runs` row per run (and a `run_id=null, send_ok=false` row when a send fails — not dropped).
- [X] T017 [P] [US1] Integration test `tests/integration/test_api_experiments.py` (cites `007/FR-001`, `007/FR-002`, `007/FR-003`, `007/FR-012`, `007/FR-015`, `007/SC-001`): identical arms → `422`; missing permission → `409`; valid create → `201`; poll `GET status` to finished with a timeout (fakes complete fast), then `GET result` shows both arms + the recorded diff.
- [X] T018 [P] [US1] Integration test `tests/integration/test_ui_experiments.py` (cites `007/FR-013`): the Experiments screen renders arm A/B editors, Start, progress, and the side-by-side table (api_client monkeypatched).

### Implementation

- [X] T019 [US1] Implement `src/kestrel/experiments/results.py` (`arm_result`, `build_comparison`) over stored runs, using `stats` + `pricing` and `report.owasp.TESTED` labels. Make T015 pass.
- [X] T020 [US1] Implement `src/kestrel/experiments/engine.py` `run_experiment`: seed selection per family (recorded), A-then-B order, per-run reuse of `execute_run` / `execute_adaptive_run`, per-arm `JudgeClient`/`AttackerClient`, `experiment_runs` recording, write-back always on (cold-arm toggle arrives in US3). Make T016 pass.
- [X] T021 [US1] Add schemas to `src/kestrel/api/schemas.py`: `CreateExperimentRequest` (arm_a/arm_b `ArmIn`, `CapsIn`, families default all, reps default 3) with an **arms-must-differ** validator; `ExperimentStatusOut`, `ArmResultOut`, `ComparisonOut`, `ExperimentResultOut`, `ExperimentSummaryOut`.
- [X] T022 [US1] Add endpoints to `src/kestrel/api/main.py`: `POST /api/experiments` (validate, permission/terms gate, one-running-per-target, claim row, schedule `run_experiment` via `asyncio.create_task` and store the handle on `app.state` to avoid GC — not FastAPI `BackgroundTasks` — `201`), `GET /api/experiments/{id}/status`, `GET …/result`, `GET /api/experiments`. Make T017 pass. *(depends T019, T020, T021)*
- [X] T023 [US1] Add `create_experiment`, `experiment_status`, `experiment_result`, `list_experiments` to `ui/api_client.py`.
- [X] T024 [US1] Add `render_experiments(config, targets)` to `ui/app.py` (arm editor, families/reps/caps, Start, live progress, side-by-side table) and call it from `main()`; caption that retrieval on/off only affects **adaptive** mode (no effect single-turn). Make T018 pass. *(depends T023)*

**Checkpoint**: MVP — a user can run a 2-arm experiment and read the comparison.

---

## Phase 4: User Story 2 — Trust the comparison (P2)

**Goal**: confirmed never mixed with suspected; no bare percentage at small N.

**Independent test**: a small experiment shows each arm's rate split into confirmed/suspected and a comparison with a significance indicator + small-sample caveat, never a bare %.

- [X] T025 [P] [US2] Test `tests/unit/test_experiment_honesty.py` (cites `007/FR-006`, `007/FR-007`, `007/SC-002`, `007/SC-003`): confirmed and suspected are reported separately (never one number); a small-N comparison carries the significance indicator **and** the caveat; a rate over zero scored runs is "no data", not 0%.
- [X] T026 [US2] Harden `src/kestrel/experiments/results.py` + `ExperimentResultOut`: distinct confirmed/suspected fields, the small-sample caveat string, and the "no data" sentinel. Make T025 pass. *(results.py — after T019)*
- [X] T027 [US2] Present the split + caveat in the `ui/app.py` side-by-side table; never render a bare % at small N. *(app.py — after T024)*

---

## Phase 5: User Story 3 — Control warming and order (P2)

**Goal**: a cold arm (write-back off) is not warmed by the other; order + warming recorded.

**Independent test**: run with one arm cold → that arm's runs did not write back; the experiment records the order and which arm(s) wrote back.

- [X] T028 [P] [US3] Test `tests/unit/test_experiment_warming.py` (cites `007/FR-005`, `007/SC-005`): a cold arm's runs keep `memory_written = null` (write_back not called); the warm default writes back; `run_order` is recorded (A=1, B=2).
- [X] T029 [US3] Engine: call `write_back(...)` only when `arm.write_back`; set `run_order` as each arm starts; carry the warming summary into the result. `src/kestrel/experiments/engine.py`. Make T028 pass. *(after T020)*
- [X] T030 [US3] Surface `order` + `warming` in `ExperimentResultOut` / result aggregation. `src/kestrel/experiments/results.py`. *(after T026)*

---

## Phase 6: User Story 4 — Bounded and safe experiments (P2)

**Goal**: hard caps with a clean stop + partial results; no secret ever in an arm/result/log; progress reported.

**Independent test**: a low cap stops the experiment within the wall-clock limit, returns a usable partial comparison naming the cap; no arm/output contains a target header or key.

- [X] T031 [P] [US4] Test `tests/unit/test_experiment_caps.py` (cites `007/FR-008`, `007/SC-004`): each of max_runs / token_budget_total / wall_clock_s trips a clean stop at a run boundary, sets the matching `stopped_reason`, and leaves a usable partial result; no run left in progress.
- [X] T032 [P] [US4] Test `tests/integration/test_experiment_secrets.py` (cites `007/FR-011`, `007/SC-007`): no target header value or key appears in a stored arm, the status/result JSON, or the logs.
- [X] T033 [US4] Engine: check all three caps **before each run**; on a hit set `stopped_reason`, `status=stopped`, `finished_at`, and return cleanly. `src/kestrel/experiments/engine.py`. Make T031 pass. *(after T029)*
- [X] T034 [US4] Status/progress: planned vs completed, tokens, cost, per-arm progress, and the partial result while running. `src/kestrel/api/main.py` + `results.py`. *(after T022)*
- [X] T035 [US4] Guarantee secret-safety: arms persist only model names + numeric settings; headers are resolved per run (as `POST /api/runs` does) and never copied into an arm row, a payload, a result, or a log. Verify with T032. *(engine/schemas/store — after T033)*

---

## Phase 7: User Story 5 — OWASP-mapped, shareable report (P3)

**Goal**: a downloadable report naming both attacker models + versions and judges, OWASP-mapped.

**Independent test**: a finished experiment's report names both attacker models + versions and maps each category row to OWASP; downloads as Markdown and HTML.

- [X] T036 [P] [US5] Test `tests/unit/test_experiment_report.py` (cites `007/FR-009`, `007/FR-010`, `007/FR-014`, `007/SC-006`, `007/SC-008`): the report names both arms' attacker models + versions and judges; a per-OWASP table maps every row to an OWASP LLM Top 10 class; Markdown + HTML render; run-derived text is fenced/escaped.
- [X] T037 [US5] Implement `src/kestrel/report/experiment.py` (`build_experiment_report`, `render_experiment_markdown`) reusing `report.render.render_html` and `report.owasp`. Make T036 pass.
- [X] T038 [US5] Add `GET /api/experiments/{id}/report?format=md|html` to `src/kestrel/api/main.py` (read-only). *(after T034)*
- [X] T039 [US5] Add `experiment_report(id, fmt)` to `ui/api_client.py` and a Download control to `render_experiments`. *(after T027)*

---

## Phase 8: Polish & cross-cutting

- [X] T040 [P] [Polish] e2e `tests/e2e/test_us1_ab_experiment.py` (cites `007/SC-009`, `007/FR-003`, `007/FR-005`, `007/FR-006`): a 2-arm experiment vs the HS-code target, N=1, retrieval **off** (arm A, cold) vs **on** (arm B, warm), polled to finished, asserting a comparison with split rates, a significance caveat, the recorded diff/order/warming, and arm A's `memory_written = null`.
- [X] T041 [P] [Polish] Document the A/B harness in `README.md` (status + Experiments screen) and note the `KESTREL_MODEL_PRICES` setting.
- [X] T042 [Polish] `uv run ruff check src ui tests`; `uv run mypy src` (advisory); full suite with `--cov=src --cov-fail-under=85`.
- [X] T043 [Polish] Run `scripts/check_spec.py` and `scripts/check_traceability.py`; confirm every 007 FR/SC is cited by a 007-scoped test, or add a `specs/007-ab-harness/traceability.md` justification (scoped `007/FR-0xx:`); run the quickstart.md walkthrough.

---

## Dependencies & execution order

- **Setup (T001–T002)** → **Foundational (T003–T014)** blocks everything.
- Within Foundational: T003→T004 (runs.py); T005→T006→T008 (store.py, sequential); T009→T010 (settings); T011→T012 (stats); T013→T014 (pricing). The three impl pairs (store, settings, stats, pricing) are independent of each other.
- **US1 (T015–T024)** is the MVP; T019/T020/T021 before T022; T023 before T024.
- **US2/US3/US4** build on US1's engine (`engine.py`: T020→T029→T033, sequential) and results (`results.py`: T019→T026→T030, sequential) and API (`main.py`: T022→T034→T038, sequential).
- **US5 (T036–T039)** after US4's API/UI edits (same files).
- **Polish (T040–T043)** last; T040 validates US1+US3 end-to-end.

### File-conflict (sequential, not [P])

- `src/kestrel/store.py`: T006 → T008.
- `src/kestrel/experiments/engine.py`: T020 → T029 → T033 (→ T035).
- `src/kestrel/experiments/results.py`: T019 → T026 → T030.
- `src/kestrel/api/main.py`: T022 → T034 → T038.
- `ui/app.py`: T024 → T027 → T039. `ui/api_client.py`: T023 → T039.

### Parallel opportunities

- Setup T002 ∥ T001's follow-up.
- Foundational test tasks T003/T005/T007/T009/T011/T013 are all [P]; impl T012 ∥ T014 (different files).
- Each story's test tasks (T015–T018, T025, T028, T031/T032, T036) are [P] — all new files.

## Implementation strategy

- **MVP = Phases 1–3** (Setup + Foundational + US1): run a 2-arm experiment and read the comparison. Stop and validate.
- Then layer US2 (honesty) → US3 (warming) → US4 (caps/safety) → US5 (report), each independently testable.
- Finish with the e2e and the QA gate (ruff, coverage ≥ 85, traceability).

## Notes

- Tests-first: write the test, see it fail, then implement.
- **No attack text** anywhere — reuse the existing library and loops (behaviour only).
- **Secrets never leave the vault** (Principle IV): arms hold model names + settings only.
- Cold-arm write-back is the one justified Principle V deviation (plan Complexity Tracking) — it is opt-in and recorded.
- The implementation PR from `007-impl` carries **`Spec-PR: #4`** in its body.
