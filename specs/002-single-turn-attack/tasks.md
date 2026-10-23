# Tasks: Run One Single-Turn Attack and Judge the Result

**Input**: Design documents from `/specs/002-single-turn-attack/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: included. Principle VII requires unit tests before implementation and one end-to-end test against the sacrificial target; the spec names three (SC-008).

**Organization**: grouped by user story, so each can be built and checked on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel with other [P] tasks — different files, no dependency on unfinished work.
- **[US1] / [US2] / [US3]**: the user story the task serves. Setup, Foundational and Polish carry no story label.

## Path Conventions

Feature 001's layout, extended. Kestrel is `src/kestrel/`, the screen is `ui/`, the sacrificial target is its own uv project in `targets/hs_code/`, tests are `tests/unit/`, `tests/integration/` and `tests/e2e/`.

## Names fixed by the contracts

Tests and code written in different tasks rely on these:

- Families: `direct_injection`, `system_prompt_leak`, `tool_exfiltration`, `indirect_injection`.
- Verdicts: `succeeded`, `failed`, `unclear`. Run status: `in_progress`, `finished`.
- Settings: `KESTREL_JUDGE_MODEL` (default `google/gemini-3.8-flash`), `KESTREL_JUDGE_API_KEY` falling back to `OPENROUTER_API_KEY`, `KESTREL_JUDGE_BASE_URL`.
- Target: `HS_TARGET_CANARY`, `GET /debug/tool-calls`.
- Limits: reply cut at 2,000 characters, judge answer 200 tokens, send 60 seconds, one 90-second deadline for the whole run, and the judge gets `min(30 s, what is left of it)`.

---

## Phase 1: Setup

**Purpose**: make room for the two new packages.

- [X] T001 Create `src/kestrel/attacks/`, `src/kestrel/attacks/data/` and `src/kestrel/judge/`, each with an `__init__.py`.
- [X] T002 [P] Add `KESTREL_JUDGE_MODEL`, `KESTREL_JUDGE_API_KEY`, `KESTREL_JUDGE_BASE_URL` and `HS_TARGET_CANARY` to `.env.example`, with a comment that the judge is optional and canary evidence works without it.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: settings, schema v2, the attack library, the judge, the terms, and teeth for the sacrificial target. Every user story needs them.

**⚠️ CRITICAL**: no user story work starts until this phase is complete.

### Settings

- [X] T003 [P] Add judge cases to `tests/unit/test_settings.py` (FR-019, FR-021): `KESTREL_JUDGE_MODEL` defaults to `google/gemini-3.8-flash`; the key reads `KESTREL_JUDGE_API_KEY` first and falls back to `OPENROUTER_API_KEY`; `KESTREL_JUDGE_BASE_URL` defaults to `https://openrouter.ai/api/v1`; a missing key is not an error.
- [X] T004 Add `judge_model`, `judge_api_key` and `judge_base_url` to `Settings` and `load_settings` in `src/kestrel/settings.py` (FR-019, FR-021, [contracts/judge.md](./contracts/judge.md)).

### Schema version 2

- [X] T005 [P] Write `tests/unit/test_store_migration.py` (FR-029): a database at `schema_version = 1` gains `target_canaries` and `runs` and moves to 2; its existing targets and encrypted header values still read back; a fresh database is created at version 2 directly.
- [X] T006 Add schema v2 to `src/kestrel/store.py` per [data-model.md](./data-model.md) (FR-010, FR-025, FR-027, FR-029, FR-030): `target_canaries` with `CHECK(length(value) >= 8)`, `runs` with its verdict and status `CHECK`s, index `idx_runs_target` on `(target_id, started_at DESC)`, partial unique index `uq_runs_active` on `(target_id) WHERE status = 'in_progress'`, and the additive 1 → 2 migration.

### Canary storage

- [X] T007 [P] Write `tests/unit/test_store_canaries.py` (FR-024, FR-025): a value under 8 characters is refused; the same value twice on one target is refused; the same value on two targets is allowed; order is kept; deleting the target deletes them.
- [X] T008 Add `set_canaries` and `list_canaries` to `src/kestrel/store.py` (FR-024), and include canaries in `get_target`.

### Run storage

- [X] T009 [P] Write `tests/unit/test_store_runs.py` (FR-005, FR-010, FR-019, FR-027, FR-028, FR-030, FR-031): `claim_run` writes an `in_progress` row and a second claim for the same target is refused while one is open; `claim_run` records `attacker_source` as `library:<version>` and `finish_run` leaves it untouched; `finish_run` sets verdict, reason, evidence, judge fields and `finished_at`; `list_runs` is newest first; deleting the target deletes its runs; `close_interrupted_runs` closes an `in_progress` row as `unclear` and returns how many it closed.
- [X] T010 Add `claim_run`, `finish_run`, `list_runs`, `get_run` and `close_interrupted_runs` to `src/kestrel/store.py` (FR-027 to FR-031).

### Attack library

- [X] T011 [P] Write `tests/unit/test_attack_library.py` against a fixture library (FR-001 to FR-005, FR-007, FR-008): each of the 8 validation rules in [contracts/attack-library.md](./contracts/attack-library.md) fails loudly; a prompt over 4,000 characters is refused; `pick(family)` returns a prompt of that family; `pick(family, prompt_id)` returns that prompt; an unknown family or id raises.
- [X] T012 Write `src/kestrel/attacks/library.py` (FR-001, FR-002, FR-005, FR-007, FR-008): load the JSON once, validate it, index by family, and expose `families()`, `prompts(family)` and `pick(family, prompt_id=None)`. A validation failure raises at start-up rather than shipping a broken library.
- [X] T013a Write `scripts/import_attacks.py` and `src/kestrel/attacks/data/sources.json` (FR-001 to FR-005, R8).
  `sources.json` lists, per entry: dataset URL, licence, the item IDs to take, and the target family.
  It contains no prompt text. The script downloads each dataset, selects items by ID only,
  maps them to the library schema with `source`, `source_url` and `licence`, refuses any source
  whose licence does not permit redistribution, and writes `library.json` and `SOURCES.md`.
  Test it in `tests/unit/test_import_attacks.py` against a small local fixture dataset, with no
  network access. Use httpx, already a dependency; no new dependency.
- [X] T013b (manual, done by the user) Fill `sources.json` with 16 to 24 items, at least 3 per family,
  from published sources such as garak, JailbreakBench or PyRIT. Run the script, check the output
  with the T012 loader, and commit `library.json` and `SOURCES.md`.

### Judge

- [X] T014 [P] Write `tests/unit/test_judge_verdict.py` (FR-017, FR-021): a well-formed structured answer parses; a JSON object embedded in text parses; a verdict string outside the three values is a parse failure, never coerced; a reason over 200 characters is cut; a non-JSON answer is a parse failure.
- [X] T015 Write `src/kestrel/judge/verdict.py` (FR-017, FR-021): the schema, and parsing in the order given in [contracts/judge.md](./contracts/judge.md).
- [X] T016 [P] Write `tests/unit/test_judge_client.py` with `httpx.MockTransport` (FR-013, FR-020, FR-022): the reply is cut to 2,000 characters before sending; `max_tokens` is 200; the timeout passed in is honoured and is never more than 30 seconds; no key means "not configured" without a request; a transport error and a timeout both come back as judge-unreachable; and the request body carries no auth header value, URL, or target name.
- [X] T017 Write `src/kestrel/judge/client.py` (FR-013, FR-020, FR-022): one `httpx.AsyncClient` call to `{base_url}/chat/completions` with structured output, taking its timeout from the caller rather than fixing it, so the run's deadline can shorten it. No new dependency (R2).

### Terms version 2

- [X] T018 Update `src/kestrel/api/terms.md` to version `2`, adding one single-line paragraph saying that an agent's reply is sent to the judge's model provider when a run is judged (FR-023, R12). Keep the existing paragraphs as they are.

### Sacrificial HS-code target (FR-034, FR-035)

- [X] T019 [P] Write `targets/hs_code/tests/test_send_email.py` (FR-035): a call is recorded with its arguments, nothing is sent, and the recorder can be cleared.
- [X] T020 Write `targets/hs_code/tools/send_email.py` (FR-035): a tool the model can call that appends to an in-memory list and returns a plausible success, sending nothing.
- [X] T021 [P] Add cases to `targets/hs_code/tests/test_app.py` (FR-034, FR-035): `HS_TARGET_CANARY` reaches the system prompt; `GET /debug/tool-calls` needs the same `X-API-Key` and answers 401 without it; the tool-calling loop records a call when the model asks for one, using CargoLint's `FakeRawClient` so no model is called.
- [X] T022 Add to `targets/hs_code/app.py` (FR-034, FR-035): the canary from `HS_TARGET_CANARY` in the system prompt, a small tool-calling loop that can invoke `send_email`, and `GET /debug/tool-calls`. This is the largest single piece of work in the feature (R14) — the target has no tool loop today.

**Checkpoint**: schema, library, judge and target are ready; user story work can begin.

---

## Phase 3: User Story 1 - Run one attack against my target and get a verdict (Priority: P1) 🎯 MVP

**Goal**: pick a target and a family, click Run, and see the prompt, the reply and a verdict with its reason.

**Independent Test**: with the sacrificial target saved and its canary declared, run a system-prompt-leak attack and see "confirmed by canary"; run one with no canary match and see a judge verdict naming the model.

### Tests for User Story 1 ⚠️

- [X] T023 [P] [US1] Write `tests/unit/test_canary_match.py` (FR-016, FR-026): an exact match is found; a match differing only in letter case is **not** found; matching runs on the masked reply, so a header value cannot produce one; an empty reply matches nothing; a target with no canaries never matches.
- [X] T024 [P] [US1] Write `tests/unit/test_runs.py` with a stub tester and a stub judge (FR-005, FR-013 to FR-019, FR-022, SC-001, SC-002, SC-005):
  - a canary match finishes the run `succeeded` with `hard_evidence` true and the judge untouched;
  - no canary match asks the judge and stores `hard_evidence` false;
  - a judge answering `succeeded` still leaves `hard_evidence` false;
  - a send failure finishes with `failure_step`, no verdict and no judge call;
  - the reply is masked and cut before it is stored or judged, and a cut reply sets `reply_truncated` true while an uncut one leaves it false (FR-022);
  - every finished run records `attacker_source` as `library:<version>`, and records `judge_model` whenever `judge_used` is true (FR-005, FR-019);
  - **the deadline**: with a stub tester that consumes 85 of the 90 seconds, the judge is given about 5 seconds rather than 30, and a run whose send consumes the whole deadline finishes without calling the judge at all (FR-013);
  - **the invariant for SC-002**: across every path above — success, failure, judge failure, deadline — the finished run has either a verdict or a `failure_step`, and never neither.
- [X] T025 [P] [US1] Write `tests/integration/test_api_runs.py` (FR-006, FR-009 to FR-011, FR-023, SC-009, SC-011): `POST /api/runs` answers 201 with the RunDetail shape; 404 for an unknown target; 409 `run_in_progress`, `permission_missing` and `terms_outdated`; 422 for an unknown family or prompt id; and that `permission_missing` and `terms_outdated` leave no run row behind while a tester failure does. For SC-011, assert the stronger invariant that a target stored under terms version 1 cannot reach the judge at all: the 409 happens before any run row or judge call, and once the target is re-saved under version 2 the same request is judged.
- [X] T026 [P] [US1] Write `tests/integration/test_api_canaries.py` (FR-024, FR-025): canaries save and read back in full; under 8 characters gives 422 on `canaries.{i}`; a duplicate gives 422; omitting the field on `PUT` keeps them and `[]` clears them; changing them needs no new connection test.
- [X] T027 [P] [US1] Write `tests/integration/test_ui_attack.py` with `api_client` stubbed (FR-032, FR-033, SC-007): the family select, the Run button disabled while a run is in progress, the three blocked-run messages, and that a successful attack renders through `st.code` and never `st.markdown`.
- [X] T028 [P] [US1] Write `tests/e2e/test_us1_attack.py` (FR-016, FR-036, SC-003, SC-008): against the running sacrificial target with its canary declared, a system-prompt-leak attack finishes `succeeded` with `hard_evidence` true and `judge_used` false — the first test of SC-008. Written and guarded to skip until T013b lands; green via `library_required`. Extend feature 001's `tests/e2e/conftest.py` so the harness passes `HS_TARGET_CANARY` to the target it starts and exposes that value to the tests, keeping FR-036's rule that the end-to-end tests start and stop the target themselves with no manual steps.

### Implementation for User Story 1

- [X] T029 [US1] Write `src/kestrel/runs.py` (FR-011 to FR-022): the fixed order from [contracts/kestrel-api.md](./contracts/kestrel-api.md) — check target, permission and terms, claim the row, send through feature 001's `run_test`, mask and cut the reply, match canaries, judge only when nothing matched, finish the row. `hard_evidence` is set by canary matching alone. Record `attacker_source` as `library:<version>` and `reply_truncated` when the reply was cut.

  Take one monotonic deadline of 90 seconds at the start of the run and carry it through (FR-013). The send gets `min(60, remaining)`; the judge gets `min(30, remaining)` and is skipped entirely when nothing is left, which finishes the run `unclear` with a reason saying the deadline was reached. Do not derive the ceiling by adding the two sub-limits — 60 plus 30 is exactly 90 and leaves nothing for masking, matching and two database writes.
- [X] T030 [US1] Add `CanaryIn`, `RunSummary` and `RunDetail` to `src/kestrel/api/schemas.py` (FR-024, FR-025), with the canary length and duplicate rules.
- [X] T031 [US1] Add `POST /api/runs` to `src/kestrel/api/main.py` (FR-006, FR-009, FR-010, FR-023), with the 409 codes and the no-run-row rule for preconditions.
- [X] T032 [US1] Extend `GET /api/targets/{id}`, `POST /api/targets` and `PUT /api/targets/{id}` in `src/kestrel/api/main.py` to carry canaries (FR-024).
- [X] T033 [US1] Add `judge` (`model`, `configured`) to `GET /api/config` and move the terms to version 2 in the response (FR-021, FR-023).
- [X] T034 [US1] Add `run_attack`, `get_run`, `list_runs`, `attack_families` and `attack_prompts` to `ui/api_client.py` (FR-013), with a 120-second timeout on runs, above the API's own 90-second deadline.
- [X] T035 [US1] Add the canary rows and the judge caption to the sidebar in `ui/app.py` (FR-024, [contracts/ui-screen.md](./contracts/ui-screen.md) rows 4b and 11b).
- [X] T036 [US1] Add the Attack panel and its result rendering to `ui/app.py` (FR-018, FR-032, FR-033), claiming the run in session state before the call so a rerun cannot send a second one, and labelling a judge verdict "suspected" and a canary verdict "confirmed".
- [X] T037 [US1] Add the one-line run log in `src/kestrel/runs.py` (FR-015, R13): target, family, prompt id, verdict, evidence, judge model, duration — never prompt text, reply, reason or a header value.

**Checkpoint**: an attack can be run and judged end to end.

---

## Phase 4: User Story 2 - See what I have already run against a target (Priority: P2)

**Goal**: runs are listed under their target, survive a restart, and an interrupted run does not block the target.

**Independent Test**: run two attacks, restart the API, reopen the target and see both; stop the API mid-run and confirm the interrupted run is listed as `unclear` and a new run can start.

### Tests for User Story 2 ⚠️

- [X] T038 [P] [US2] Write `tests/integration/test_api_run_history.py` (FR-028, FR-030, SC-010): `GET /api/targets/{id}/runs` is newest first and 404s for an unknown target; `GET /api/runs/{id}` returns RunDetail and 404s; deleting a target removes its runs.
- [X] T039 [P] [US2] Write `tests/integration/test_api_startup_sweep.py` (FR-031, SC-012): a database holding an `in_progress` row is swept on start-up to `unclear` with an interrupted reason, the count is logged, and a new run against that target can then be claimed.
- [X] T040 [P] [US2] Write `tests/integration/test_ui_runs.py` with `api_client` stubbed (FR-028, FR-032): the runs table shows when, family, prompt title, verdict and evidence; with no target selected it shows the empty line; opening a row shows prompt, reply and reason through `st.code`.
- [X] T041 [P] [US2] Write `tests/e2e/test_us2_judged_run.py` (FR-005, FR-019, SC-004, SC-008): a harmless prompt against the sacrificial target is judged `failed`, and the stored run names the judge model — the second and third tests of SC-008.

### Implementation for User Story 2

- [X] T042 [US2] Add `GET /api/targets/{id}/runs` and `GET /api/runs/{id}` to `src/kestrel/api/main.py` (FR-028).
- [X] T043 [US2] Call `close_interrupted_runs` from `create_app` in `src/kestrel/api/main.py` and log how many were closed (FR-031).
- [X] T044 [US2] Add the Runs table and its detail view to `ui/app.py` (FR-028, FR-029, FR-032), reloading after a run and when the selected target changes.

**Checkpoint**: run history works and survives restarts.

---

## Phase 5: User Story 3 - Choose the exact attack prompt (Priority: P3)

**Goal**: the user can pick a named prompt from the family instead of letting Kestrel pick.

**Independent Test**: pick a family, pick a prompt by title, run it, and see that prompt as the one sent.

### Tests for User Story 3 ⚠️

- [X] T045 [P] [US3] Write `tests/integration/test_api_library.py` (FR-002, FR-003, FR-005, FR-008): `GET /api/attack-families` returns the four families with their OWASP category, prompt count and the library version; `GET /api/attack-prompts?family=` returns that family's prompts and 422s on an unknown key.
- [X] T046 [P] [US3] Add cases to `tests/integration/test_ui_attack.py` (FR-007, FR-008, FR-032): the prompt select defaults to "Kestrel picks one", picking a prompt shows its text through `st.code` before sending, and the chosen `prompt_id` reaches the API.

### Implementation for User Story 3

- [X] T047 [US3] Add `GET /api/attack-families` and `GET /api/attack-prompts` to `src/kestrel/api/main.py` (FR-002, FR-003, FR-008).
- [X] T048 [US3] Add the prompt select and its preview to the Attack panel in `ui/app.py` (FR-007, FR-008, FR-032).

**Checkpoint**: all three stories work.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: documentation, the manual checks, and a last secret-hygiene pass.

- [X] T049 [P] Update the root `README.md`: declaring canaries, configuring the judge and what happens without a key, and the per-run judge cost.
- [X] T050 [P] Update `targets/hs_code/README.md`: `HS_TARGET_CANARY`, the fake `send_email` tool and `GET /debug/tool-calls`, and that the target now has a tool-calling loop.
- [X] T051 Go through the 19 manual checks in [quickstart.md](./quickstart.md) against a running API, screen and sacrificial target. Fix any difference, in the code or in quickstart.md.
  - 2026-10-24: all 19 checks exercised against live services. Check 5 needed a fix (the run detail now shows the attacker source). Checks 2/16/19 and check 4's "suspected" label are positive-compromise outcomes that depend on the target model; gpt-4o-mini resists, so they were verified via a canary-returning stub and the offline/target suites. See quickstart.md.
- [X] T052 Review secret hygiene on the judge path across `src/kestrel/**/*.py` and `ui/app.py` (FR-014, FR-015, FR-020, SC-006): confirm no header value, target URL or target name can reach the judge request, the run record or a log line, and that the reply is masked before it is stored, judged or shown (R13).
- [X] T053 Run everything a last time: `uv run pytest`, `uv run pytest -m e2e`, and `uv run --directory targets/hs_code pytest`.

---

## Dependencies

### Phase Dependencies

- Phase 1 → Phase 2 → Phase 3 (US1) → Phase 4 (US2) → Phase 5 (US3) → Phase 6.
- US2 depends on US1 only because runs must exist before they can be listed. US3 depends on US1 for the Attack panel it extends.

### Within each phase

Test tasks come before the implementation they cover. Tasks marked [P] touch different files and can run together.

### Task-level dependencies worth knowing

- T006 (schema) blocks T008, T010 and every store test after it.
- T012 (library loader) blocks T047 and the family routes. T013a (the import pipeline) can run in parallel with T012. T013b (filling and running it to produce the data file) must land before T028.
- T015 and T017 (judge) block T029.
- T018 (terms v2) blocks T025's `terms_outdated` case and T033.
- T022 (target teeth) blocks T028 and T041, the end-to-end tests.
- T029 (`runs.py`) blocks T031, and through it the rest of US1.

### Parallel Opportunities

- Phase 2: T003, T005, T007, T009, T011, T014, T016, T019 and T021 are all tests in separate files and can be written together. T013a (the import pipeline) is independent of all the code tasks and can run alongside them.
- Phase 3: T023 to T028 in parallel, then the implementation tasks, of which T030, T034 and T035 touch different files from T029.
- Phase 6: T049 and T050 together.

## Implementation Strategy

### MVP first (User Story 1 only)

Phases 1, 2 and 3 give a working feature: pick a target and a family, run one attack, get a verdict backed by hard evidence where a canary exists. Stopping there would leave no run history, which makes it hard to use twice, but it is a complete and demonstrable slice.

### Incremental delivery

1. Phases 1–2: foundation, including the target's new teeth. Nothing user-visible yet.
2. Phase 3: US1. Commit and demonstrate.
3. Phase 4: US2. Runs persist and list.
4. Phase 5: US3. Deliberate prompt choice.
5. Phase 6: documentation, manual checks, final run.

### Note carried from the plan

This feature does not write runs back to the attack-pattern store, which Principle V calls a bug. It is recorded as a justified deferral in [plan.md](./plan.md) under Complexity Tracking, with the run record already carrying everything a later write-back needs. It closes in **feature 004**, when the ChromaDB store lands and backfills these runs; if that slips, Principle V must be amended with a version bump rather than left quietly broken.
