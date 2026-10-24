# Tasks: Run a Multi-Turn Adaptive Attack and Judge the Result

**Input**: Design documents from `/specs/003-adaptive-attack/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: included. Principle VII requires unit tests before implementation and one end-to-end test against the sacrificial target (SC-009).

**Organization**: grouped by user story. Feature 003 extends feature 002; where behaviour is identical it is reused, not rebuilt, so many tasks are additions to existing modules rather than new ones.

**No attack prompt text** appears in any task; tasks describe behaviour and structure only.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: parallelizable — different files, no dependency on unfinished work.
- **[US1]/[US2]/[US3]**: the user story a task serves. Setup, Foundational and Polish carry no story label.

## Names fixed by the contracts

Tests and code in different tasks rely on these ([research.md](./research.md), [contracts/](./contracts/)):

- Env: `KESTREL_ATTACKER_MODEL` (default `deepseek/deepseek-v3.2`), `KESTREL_ATTACKER_API_KEY` (falls back to `OPENROUTER_API_KEY`), `KESTREL_ATTACKER_BASE_URL` (default `https://openrouter.ai/api/v1`); `KESTREL_ADAPTIVE_MAX_TURNS` (6), `KESTREL_ADAPTIVE_TOKEN_BUDGET` (40000), `KESTREL_ADAPTIVE_TIME_LIMIT_S` (300); `KESTREL_JUDGE_MODEL` unchanged.
- Run modes: `single_turn`, `adaptive`. Stopping conditions: `succeeded`, `turn_cap`, `token_budget`, `time_limit`, `send_failed`, `attacker_failed`, `interrupted`.
- Terms version becomes `3`.

---

## Phase 1: Setup

- [X] T001 Create `src/kestrel/attack/` with an `__init__.py` (one-line docstring: the adaptive attacker/judge loop).
- [X] T002 [P] Add `langgraph` to `pyproject.toml` dependencies with a one-line justification (Principle X: the attacker/judge loop is a graph; in the fixed MVP stack), and run `uv sync`. Model calls stay on `httpx`; no model SDK is added.
- [X] T003 [P] Add the attacker and adaptive-cap environment variables to `.env.example` with a note that the attacker is optional (an adaptive run needs it; single-turn and canary evidence do not) (FR-010, FR-011, FR-014).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: settings, schema v3, terms v3 and the judge's progress note — shared by every story.

**⚠️ CRITICAL**: no user story work starts until this phase is complete.

- [X] T004 [P] Add cases to `tests/unit/test_settings.py` (FR-010, FR-011, FR-014): `KESTREL_ATTACKER_MODEL` defaults to `deepseek/deepseek-v3.2`; the attacker key reads `KESTREL_ATTACKER_API_KEY` then falls back to `OPENROUTER_API_KEY`; `KESTREL_ATTACKER_BASE_URL` default and trailing-slash trim; `attacker_configured` is false with no key; `KESTREL_ADAPTIVE_MAX_TURNS`/`_TOKEN_BUDGET`/`_TIME_LIMIT_S` default to 6/40000/300 and parse from env; blanks count as unset.
- [X] T005 Add the attacker and adaptive-cap fields to `Settings` and `load_settings` in `src/kestrel/settings.py` (FR-010, FR-011, FR-014): `attacker_model`, `attacker_api_key` (repr-hidden, fallback), `attacker_base_url`, `attacker_configured` property, `adaptive_max_turns`, `adaptive_token_budget`, `adaptive_time_limit_s`.
- [X] T006 [P] Write `tests/unit/test_store_migration_v3.py` (FR-020): a database at `schema_version = 2` gains the new `runs` columns and the `run_turns` table and moves to 3; existing runs read back as `mode = 'single_turn'` with null adaptive fields and their prompt/reply intact; a fresh database is built at version 3; a database at version 1 migrates 1→2→3; an unknown newer version is refused.
- [X] T007 Add schema v3 to `src/kestrel/store.py` per [data-model.md](./data-model.md) (FR-012, FR-015, FR-019, FR-020): add the `runs` columns (`mode` with `CHECK` in `single_turn`/`adaptive`, `attacker_model`, `turn_budget`, `turns_used`, `token_budget`, `tokens_used`, `time_limit_s`, `stopping_condition`, `succeeded_turn`), create `run_turns` (FK cascade, `position`, `attacker_message`, `reply_text`, `reply_truncated`, `judge_verdict`, `judge_reason`, `judge_progress`, `created_at`) with index `idx_run_turns_run`, and the additive 2→3 migration.
- [X] T008 [P] Write `tests/unit/test_store_run_turns.py` (FR-020, FR-022): turns append in order and read back by run; a run claimed with `mode='adaptive'` records its budgets; `finish_run` records `stopping_condition`, `succeeded_turn`, `attacker_model`, turns/tokens used; deleting the run (and the target) deletes its `run_turns`.
- [X] T009 Extend `src/kestrel/store.py` (FR-012, FR-015, FR-019, FR-020): `claim_run` accepts `mode` and the adaptive budgets; `finish_run` accepts the adaptive outcome fields; add `add_turn(run_id, ...)` and `list_turns(run_id)`; `get_run`/`list_runs` carry `mode`.
- [X] T010 Update `src/kestrel/api/terms.md` to version `3`, adding one single-line paragraph that an agent's replies are also sent to the **attacker** model's provider during an adaptive run (R11, FR-003). The feature-001 re-confirmation mechanism then refuses a target saved under an older terms version until it is confirmed again; confirm the feature-002 suites that read `load_terms().version` still pass (they track the constant).
- [X] T011 [P] Add cases to `tests/unit/test_judge_verdict.py` (FR-007, R6): a `progress` field parses when present; it is optional (an answer without it still parses); it is cut to the reason length cap; it is plain text.
- [X] T012 Extend the judge in `src/kestrel/judge/verdict.py` and `src/kestrel/judge/client.py` (FR-007, R6): `ParsedVerdict` gains an optional `progress` field; `RESPONSE_SCHEMA` adds `progress`; the prompt asks for a one-line "how close" note. The single-turn path ignores `progress`, so feature 002 is unchanged.

**Checkpoint**: settings, schema v3, terms v3 and the judge note are ready.

---

## Phase 3: User Story 1 - Run an adaptive attack against my target and get a verdict (Priority: P1) 🎯 MVP

**Goal**: pick a target and a family, choose Adaptive, Run, and get a verdict from a multi-turn conversation within the caps.

**Independent Test**: with the sacrificial target saved and its canary declared, run an adaptive attack and watch several turns finish with a verdict, under the turn/token/time caps.

### Tests for User Story 1 ⚠️

- [ ] T013 [P] [US1] Write `tests/unit/test_attacker_client.py` with `httpx.MockTransport` (FR-009, FR-016, FR-017): no key → not configured and no request made; the request body carries the conversation and the latest judge note but no auth header value, target URL or target name; the returned message is cut to its length cap; a transport error and a timeout both raise the attacker error; the configured model name is sent; the key rides the `Authorization` header, not the body.
- [ ] T014 [P] [US1] Write `tests/unit/test_adaptive_graph.py` with a stub attacker, stub judge and stub sender (FR-002, FR-005 to FR-013, FR-016, FR-018, FR-019, FR-021, SC-001, SC-002, SC-003, SC-005): a canary at a turn ends the run `succeeded` with `hard_evidence` true, `succeeded_turn` set, and the judge untouched that turn (SC-003); a stub judge returning `succeeded` ends the run (judge, not hard evidence); stubs that never succeed drive the loop to each cap in turn and record `stopping_condition` = `turn_cap` / `token_budget` / `time_limit`, never exceeding a cap (SC-001); a stub attacker that raises ends the run `attacker_failed`; a failed send ends the run `send_failed` with no verdict and no further turns; **the SC-002 invariant**: across every path — success, each cap, send failure, attacker failure — the finished run has either a verdict or a failure step, and a `stopping_condition`, never neither; `hard_evidence` is never set from a judge answer (SC-005); the attacker and judge stubs receive no header value, URL or name; every attacker message and every reply is masked before it is stored, and each reply is cut, before it is stored or judged (FR-021); turn one uses the library seed without calling the attacker.
- [ ] T015 [P] [US1] Write `tests/integration/test_api_runs_adaptive.py` (FR-001, FR-003, FR-004, SC-008): `POST /api/runs` with `mode="adaptive"` returns 201 with a RunDetail whose `mode` is `adaptive` and whose `turns` is the ordered conversation; 404 for an unknown target; 409 `run_in_progress`, `permission_missing`, and `terms_outdated` for a target on terms version 2, each **before any run row is created** (SC-008); 422 for an unknown family or prompt id; a single-turn request still behaves as feature 002. **Cross-mode one-run-at-a-time (FR-004)**: while an adaptive run is in progress on a target a single-turn run against it is refused `run_in_progress`, and vice versa — the lock is per target, not per mode.
- [ ] T016 [P] [US1] Write `tests/integration/test_ui_adaptive.py` with `api_client` stubbed (FR-001, FR-023, FR-024, SC-007): the Single-turn/Adaptive mode toggle is present and defaults to Single-turn; the Run button is disabled for Adaptive when `attacker.configured` is false; a finished adaptive run renders each attacker message and reply through `st.code` and never `st.markdown`; a hostile reply (HTML, script, link, image reference) is shown as characters, never rendered (SC-007; the "0 outside requests" half is manual check 15, T036).
- [ ] T017 [P] [US1] Write `tests/e2e/test_us1_adaptive.py` (FR-025, FR-026, SC-003, SC-009): against the running sacrificial target with its canary declared, an adaptive attack completes with a verdict, records the attacker model and the turns used, and stores the full conversation (`turns` non-empty). Guard it to skip without `OPENROUTER_API_KEY`; reuse feature 002's e2e harness (it already starts the target with `HS_TARGET_CANARY`). Assert the hard-evidence invariant whenever the canary surfaces, without requiring the live model to be compromised (the model-determinism caveat from feature 002).

### Implementation for User Story 1

- [ ] T018 [US1] Write `src/kestrel/attack/attacker.py` (FR-005, FR-009, FR-014, FR-016, FR-017): one `httpx.AsyncClient` call to `{base_url}/chat/completions`, built like the judge client; it receives only the conversation and the last judge note, caps the returned message length, takes a timeout from the caller (bounded by the run's remaining deadline), and raises an attacker error on no-key / transport error / timeout / unusable answer. No new dependency.
- [ ] T019 [US1] Write `src/kestrel/attack/graph.py` (FR-002, FR-005 to FR-013, FR-018, FR-019, FR-021) per [contracts/adaptive-loop.md](./contracts/adaptive-loop.md): a LangGraph `StateGraph` with attacker/send/evidence/judge/record/decide nodes and the state it carries; turn one uses the library seed; each turn sends via feature 002's `run_test` (prompt = attacker message), masks and cuts the reply, checks canaries first, judges only if none matched, stops on success, and enforces the three caps in `decide`, recording the `stopping_condition`. `hard_evidence` is set only by the canary node.
- [ ] T020 [US1] Route adaptive runs in `src/kestrel/runs.py` (FR-001): `execute_run` keeps the single-turn path; an `adaptive` request is delegated to `attack.graph`, which claims and finishes the run row. The log line is extended per T024.
- [ ] T021 [US1] Add `mode` to `RunRequest` and `POST /api/runs` in `src/kestrel/api/schemas.py` and `src/kestrel/api/main.py` (FR-001, FR-003, FR-004): accept `single_turn`/`adaptive`; for adaptive, check attacker is configured (409 or a clear error if not); reuse the feature-002 preconditions with the current terms version (now 3); return RunDetail with `turns`.
- [ ] T022 [US1] Add the Single-turn/Adaptive mode toggle to the Attack panel in `ui/app.py` (FR-001, FR-016): default Single-turn; for Adaptive, disable Run when the attacker is not configured with a caption saying so; claim the run in session state before the call, as feature 002 does; the client timeout exceeds the wall-clock cap.
- [ ] T023 [US1] Render an adaptive run's result in `ui/app.py` (FR-023, FR-024): the verdict banner (reusing feature 002's wording plus how it ended), then the conversation turn by turn — each attacker message and reply in `st.code`, each turn's judge note in `st.text`. Target and attacker text shown only as plain text.
- [ ] T024 [US1] Extend the run log line in `src/kestrel/runs.py`/`src/kestrel/attack/graph.py` (FR-017, R12): one line with target, mode, family, verdict, evidence basis, attacker model, judge model, turns used, tokens used, duration — never a message, reply, note, URL or header value.

**Checkpoint**: an adaptive attack runs end to end and returns a verdict.

---

## Phase 4: User Story 2 - Review the conversation of a run (Priority: P2)

**Goal**: the full conversation is stored, listed by kind, survives restart, and is shown turn by turn.

**Independent Test**: run an adaptive attack, restart the API, open the run, and read the whole conversation with its verdict.

### Tests for User Story 2 ⚠️

- [ ] T025 [P] [US2] Write `tests/integration/test_api_run_history_adaptive.py` (FR-020, FR-022): `GET /api/runs/{id}` returns the ordered `turns`; `GET /api/targets/{id}/runs` lists adaptive and single-turn runs together with each run's `mode`, newest first; deleting the target removes the adaptive runs and their turns.
- [ ] T026 [P] [US2] Write `tests/integration/test_api_startup_sweep_adaptive.py` (FR-022, SC-010): a database holding an `in_progress` adaptive run is swept on start-up to `unclear` with `stopping_condition = interrupted`, its already-stored turns kept, and the target can start a new run.
- [ ] T027 [P] [US2] Write `tests/integration/test_ui_runs_adaptive.py` (FR-022, FR-023): the Runs table shows a Mode column; opening an adaptive run shows the conversation turn by turn; opening a single-turn run still shows its one prompt and reply.

### Implementation for User Story 2

- [ ] T028 [US2] Carry `mode` and the conversation through the API in `src/kestrel/api/schemas.py` and `src/kestrel/api/main.py` (FR-020, FR-022): `RunSummary` gains `mode`; `RunDetail` gains `turns` populated from `list_turns`; listing and single-run endpoints keep their shape.
- [ ] T029 [US2] Add the Mode column to the Runs table and wire opening an adaptive run to the conversation view in `ui/app.py` (FR-022, FR-023), reusing the T023 renderer; single-turn runs render as in feature 002.

**Checkpoint**: run history and the conversation view work across both modes and survive restarts.

---

## Phase 5: User Story 3 - Know which attacker drove the run (Priority: P3)

**Goal**: every adaptive run names its attacker model, judge model and the budget allowed and used.

**Independent Test**: run two adaptive attacks with different configured attacker models; each run names its own model and the budget it used.

### Tests for User Story 3 ⚠️

- [ ] T030 [P] [US3] Write `tests/integration/test_api_config_adaptive.py` (FR-014, FR-015): `GET /api/config` returns an `attacker` block (`model`, `configured`), the `adaptive` caps, and `terms.version` = 3.
- [ ] T031 [P] [US3] Add cases to `tests/integration/test_api_runs_adaptive.py` or a new file (FR-015, SC-004): a finished adaptive run records and returns `attacker_model`, `judge_model`, `turn_budget`/`turns_used`, `token_budget`/`tokens_used`, `time_limit_s`; two runs made after changing the configured attacker model each name their own model.

### Implementation for User Story 3

- [ ] T032 [US3] Add the `attacker` block and the `adaptive` caps to `GET /api/config` in `src/kestrel/api/main.py` and `src/kestrel/api/schemas.py` (FR-014, FR-015), and surface terms version 3.
- [ ] T033 [US3] Show the attacker provenance in `ui/app.py` (FR-015, FR-023): a footer on an adaptive run naming the attacker model, the judge model and the budgets allowed/used, and a caption on the panel naming the attacker and caps when Adaptive is selected.

**Checkpoint**: all three stories work; every adaptive run is self-describing (Principle III).

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T034 [P] Update the root `README.md`: adaptive mode, the attacker and cap environment variables and what happens without an attacker key, the per-run cost, and that terms version 3 requires existing targets to be confirmed again.
- [ ] T035 [P] Note in `targets/hs_code/README.md` that the adaptive end-to-end test reuses the target unchanged (no target changes in this feature).
- [ ] T036 Go through the 17 manual checks in [quickstart.md](./quickstart.md) against a running API, screen and sacrificial target, including the terms-v3 re-confirm and the no-attacker-key case. Fix any difference, in the code or in quickstart.md.
- [ ] T037 Review secret hygiene on the attacker path across `src/kestrel/**/*.py` and `ui/app.py` (FR-017, R12, SC-006): confirm no header value, target URL or target name can reach the attacker request, the judge request, the stored conversation, a log line, or the screen, and that every reply is masked before it is stored, judged, sent to the attacker, or shown.
- [ ] T038 Run everything a last time: `uv run pytest`, `uv run pytest -m e2e`, and `uv run --directory targets/hs_code pytest`.

---

## Dependencies

### Phase order

- Phase 1 → Phase 2 → Phase 3 (US1) → Phase 4 (US2) → Phase 5 (US3) → Phase 6.
- US2 depends on US1 (runs and conversations must exist before they are listed/reviewed). US3 depends on US1 (the run must record the attacker before it can be shown).

### Within phases

Test tasks come before the implementation they cover. `[P]` tasks touch different files and can run together.

### Task-level dependencies worth knowing

- T005 (settings) blocks T018 (attacker client) and T019 (graph, which reads the caps).
- T007 (schema v3) blocks T009, and every store/run test after it.
- T012 (judge progress) blocks T019 (the graph feeds the note to the attacker).
- T010 (terms v3) blocks T015's `terms_outdated` case and T032.
- T018 and T019 block T020 (runs routing), and through it the rest of US1.
- T019 (graph) is the critical path; T013/T014 are its tests and come first.

### Parallel opportunities

- Phase 2: T004, T006, T008, T011 are tests in separate files and can be written together; T003 is independent.
- Phase 3: T013–T017 in parallel, then the implementation, of which T018, T021, T022 touch different files from T019.
- Phase 6: T034 and T035 together.

## Implementation Strategy

### MVP first (User Story 1)

Phases 1–3 give a working feature: pick a target, choose Adaptive, run a multi-turn attack bounded by the three caps, and get a verdict with the conversation shown. Stopping there leaves run history and provenance thinner (US2/US3) but is a complete, demonstrable slice.

### Incremental delivery

1. Phases 1–2: settings, schema v3, terms v3, judge note. Nothing user-visible yet.
2. Phase 3: US1. Commit and demonstrate.
3. Phase 4: US2. Conversations persist and list by kind.
4. Phase 5: US3. Attacker provenance recorded and shown.
5. Phase 6: docs, manual checks, hygiene, final run.

### Carried from the plan

Adaptive runs do not write back to the attack-pattern store (Principle V), the same deliberate deferral as feature 002, recorded in [plan.md](./plan.md) Complexity Tracking. It closes in feature 004 when the ChromaDB store lands, or Principle V is amended with a version bump; it must not survive the MVP.
