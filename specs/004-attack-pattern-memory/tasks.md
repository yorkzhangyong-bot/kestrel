---

description: "Task list for feature 004: attack-pattern store and per-target memory"
---

# Tasks: Learn From Every Run — Attack-Pattern Store and Per-Target Memory

**Input**: Design documents in `/specs/004-attack-pattern-memory/` (plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md)

**Tests**: included and written first (Constitution Principle VII). No test, fixture, comment or commit contains attack prompt text — behaviour only.

**Organization**: by user story. US1 (write-back) is the MVP and the foundation the others build on.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: can run in parallel (different file, no dependency on an unfinished task)
- **[Story]**: US1–US5; Setup/Foundational/Polish carry no story label

## Path conventions

Single repo: `src/kestrel/`, `ui/`, `tests/` at the root; the sacrificial target under `targets/hs_code/` (reused unchanged).

---

## Phase 1: Setup

- [X] T001 Add `chromadb` to `[project].dependencies` in `pyproject.toml` (one-line note: fixed MVP stack, Principle X) and run `uv sync`; create the package `src/kestrel/experience/__init__.py`.
- [X] T002 [P] Add a deterministic, offline stub embedding function (`StubEmbeddingFunction`, hash-based vectors) to `tests/support.py`, so every `ExperienceStore` test runs without a model download or network (research R2).

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: the store, the schema and the settings every story needs. No user story starts until this phase is done.

### Tests (write first, must fail)

- [X] T003 [P] Write `tests/unit/test_store_migration_v4.py` (FR-003 storage side): a fresh database reports schema version `4`; a version-3 database is migrated by ALTER adding `targets.description`, `runs.use_prior_experience` (default 1) and `runs.memory_written`, with existing targets and runs preserved; an unknown version still raises `UnknownSchemaVersion`.
- [X] T004 [P] Write `tests/unit/test_settings_experience.py`: `KESTREL_CHROMA_PATH` (default `data/chroma` under the repo root), `KESTREL_EXPERIENCE_PATTERN_K` (default 5) and `KESTREL_EXPERIENCE_MEMORY_CAP` (default 10) are parsed, with the same positive-integer validation as the adaptive caps.
- [X] T005 [P] Write `tests/unit/test_experience_store_core.py` (FR-001, FR-002, FR-003): with the stub embedder and a temp path, `ExperienceStore` opens one `kestrel_experience` collection, records `kestrel_store_version` in the collection metadata, reads it back on reopen, and logs a warning on a version mismatch.

### Implementation

- [X] T006 Extend `src/kestrel/store.py` to schema v4: add `targets.description TEXT`, `runs.use_prior_experience INTEGER NOT NULL DEFAULT 1`, `runs.memory_written INTEGER`; add `EXPERIENCE_RUN_COLUMNS`; allow migration from `1`/`2`/`3` → `4`; add `description` to `Target`, `use_prior_experience` and `memory_written` to `Run` (and `_run`); accept `description` in `create_target`/`update_target`; accept `use_prior_experience` in `claim_run`; add `set_memory_written(run_id, written)`. (makes T003 pass)
- [X] T007 Extend `src/kestrel/settings.py`: add `chroma_path`, `experience_pattern_k`, `experience_memory_cap` (env `KESTREL_CHROMA_PATH`, `KESTREL_EXPERIENCE_PATTERN_K`, `KESTREL_EXPERIENCE_MEMORY_CAP`) with defaults from research R12. (makes T004 pass)
- [X] T008 Implement `src/kestrel/experience/store.py` `ExperienceStore.__init__` + collection/version handling + a `count(...)` helper, per [contracts/experience-store.md](./contracts/experience-store.md). (makes T005 pass)

**Checkpoint**: the store opens, the schema migrates, settings load. User stories can begin.

---

## Phase 3: User Story 1 — Learn from every run (Priority: P1) 🎯 MVP

**Goal**: every run writes exactly one memory record; successes also write a pattern; the library is seeded idempotently; a failed write-back is loud.

**Independent Test**: run one attack; confirm exactly one new memory record for the target with safe metadata, a pattern iff it succeeded, and that a forced store failure keeps the run, flags `memory_written=false`, and logs.

### Tests (write first, must fail)

- [ ] T009 [P] [US1] Write `tests/unit/test_experience_summary.py` (FR-008, FR-013, SC-009): the summary joins the run's per-turn judge progress notes into one line with no model call; falls back to the fixed metadata template when there are none; and every result is single-line, control-char-free and within the length cap.
- [ ] T010 [P] [US1] Write `tests/integration/test_experience_seeding.py` (FR-004, FR-005, SC-002): seeding from a fixture library writes one pattern per prompt carrying family, OWASP category and a source reference and no target identity; re-seeding adds 0 duplicates.
- [ ] T011 [P] [US1] Write `tests/integration/test_writeback.py` (FR-006, FR-007, FR-009, FR-010, FR-011, FR-012, SC-001, SC-003, SC-004, SC-008, SC-011): after a run exactly one memory record exists with the required metadata and no raw reply text; a success also writes exactly one pattern (the winning attacker message(s)); a non-success writes none; a forced store failure keeps the run, sets `memory_written=false`, logs an error and reports the flag.

### Implementation

- [ ] T012 [US1] Implement `seed_patterns`, `write_memory`, `write_pattern` in `src/kestrel/experience/store.py` (deterministic ids + `upsert`), per the contract. (makes T010 pass; part of T011)
- [ ] T013 [US1] Implement `src/kestrel/experience/summary.py`: build-from-judge-notes, metadata fallback, and the fixed-shape sanitiser. (makes T009 pass)
- [ ] T014 [US1] Implement `src/kestrel/experience/writeback.py` `write_back(experience, store, run, turns)` per [contracts/writeback.md](./contracts/writeback.md): summary → write_memory → write_pattern on success → `set_memory_written(True)`; on any failure keep the run, `set_memory_written(False)`, log loudly, return False. (makes T011 pass)
- [ ] T015 [US1] Wire write-back into `src/kestrel/api/main.py`: build the `ExperienceStore` in `create_app`, `seed_patterns(library)` on start-up (idempotent; skip+warn if no library), and call `write_back` after both run paths in `start_run`; add `memory_written` to `RunSummary`/`RunDetail` in `src/kestrel/api/schemas.py` and populate it in `run_summary`/`run_detail`.

**Checkpoint**: Principle V is closed — every run is recorded, and failures are loud.

---

## Phase 4: User Story 2 — Reuse prior experience (Priority: P2)

**Goal**: warm runs prime the attacker with family-scoped patterns and this target's memory as hints; cold runs are feature 003; the choice is recorded.

**Independent Test**: two warm runs against one target; the second run's attacker receives ≥1 memory record from the first; a cold run adds 0 hints.

### Tests (write first, must fail)

- [ ] T016 [P] [US2] Write `tests/unit/test_experience_retrieval.py` (FR-016, FR-017, FR-018, SC-006, SC-014): patterns are retrieved by semantic query scoped to the current family (0 cross-family); memory is retrieved by exact `target_id` (0 cross-target); the memory selection is recent-first, capped at 10, and always keeps a same-family success past the cap.
- [ ] T017 [P] [US2] Write `tests/unit/test_hints.py` (FR-019, FR-021, SC-007): `format_hints` assembles purpose, memory and patterns in a fixed order under hints-not-commands labelling, and returns `None` when there is nothing to add.
- [ ] T018 [P] [US2] Write `tests/unit/test_attacker_hints.py` (FR-019, SC-007): `AttackerClient.next_message(hints=None)` builds the same payload as feature 003; a non-empty `hints` adds one labelled background block to the system prompt and changes nothing else.
- [ ] T019 [P] [US2] Write `tests/integration/test_runs_experience.py` (FR-014, FR-015, FR-016, SC-005): `POST /api/runs` carries `use_prior_experience` (default true), recorded on the run; with a spy attacker, a warm second run receives ≥1 memory record from the first; a cold run receives 0 patterns and 0 memory. Also assert a **single-turn** run records the chosen value (default true; a cold single-turn run records false), even though it has no retrieval effect (C1).

### Implementation

- [ ] T020 [US2] Implement `retrieve_patterns` and `retrieve_memory` in `src/kestrel/experience/store.py` per the contract (query+where for patterns; get+where then Python selection for memory). (makes T016 pass)
- [ ] T021 [US2] Implement `src/kestrel/experience/hints.py` `format_hints(purpose, patterns, memory)`. (makes T017 pass)
- [ ] T022 [US2] Extend `src/kestrel/attack/attacker.py` `next_message` with an optional `hints` parameter that adds the labelled background block; `None` keeps feature-003 behaviour. (makes T018 pass)
- [ ] T023 [US2] Extend `src/kestrel/attack/graph.py` `run_adaptive` to accept a `hint_provider` callable and call it in `attacker_node`, passing the block to `next_message(hints=...)`; the graph imports no ChromaDB.
- [ ] T024 [US2] Wire retrieval in `src/kestrel/api/main.py`: add `use_prior_experience` to `RunRequest`; thread it into `claim_run` on **both** run paths — `execute_adaptive_run`→`run_adaptive` **and** the single-turn `execute_run` (so FR-014 holds for single-turn too; C1) — adding a `use_prior_experience` parameter to `execute_run` in `src/kestrel/runs.py`; build the `hint_provider` closure (memory + purpose once, patterns per turn, with the pattern query = family goal + the **last 2 turns** of conversation; U1); add `use_prior_experience` to `RunSummary`/`RunDetail` and an `experience` block to `ConfigOut` in `src/kestrel/api/schemas.py`. (makes T019 pass)

**Checkpoint**: warm runs learn from the past; cold runs match feature 003.

---

## Phase 5: User Story 3 — Tell the attacker what a target is for (Priority: P2)

**Goal**: an optional one-line purpose description, stored non-secret and fed to the attacker as background regardless of the switch.

**Independent Test**: register a target with a purpose; it is saved, shown when editing, reaches the attacker before the first turn on warm and cold runs, and never counts as a secret.

### Tests (write first, must fail)

- [ ] T025 [P] [US3] Write `tests/integration/test_target_description.py` (FR-020): a target saves/updates with a `description` (trimmed, max 200 chars, 422 when longer); it is returned in the summary/detail; editing it alone needs no fresh connection test.
- [ ] T026 [P] [US3] Write `tests/integration/test_description_to_attacker.py` (FR-021): with a spy attacker, the purpose reaches the attacker as background on both a warm and a cold run, consuming no conversation turn.

### Implementation

- [ ] T027 [US3] Add `description` to `SaveTargetRequest`, `TargetSummary` and `TargetDetail` in `src/kestrel/api/schemas.py` (validate ≤200 chars) and wire it through `save_target`/`update_target`/`get_target`/`summary`/`detail` in `src/kestrel/api/main.py`, keeping it out of the connection fingerprint. (makes T025 pass)
- [ ] T028 [US3] Include the purpose in the `hint_provider` (warm and cold) in `src/kestrel/api/main.py`, so `format_hints` receives it; confirm no-purpose cold runs stay byte-identical to feature 003. (makes T026 pass)

**Checkpoint**: the attacker knows what it is attacking from turn one.

---

## Phase 6: User Story 4 — See what Kestrel has learned about a target (Priority: P3)

**Goal**: a per-target profile summarising its memory, secrets-free.

**Independent Test**: after several runs, the profile shows counts by family and verdict and recent summaries; an unused target shows an empty state; no secrets appear.

### Tests (write first, must fail)

- [ ] T029 [P] [US4] Write `tests/integration/test_profile.py` (FR-022, FR-023, SC-013): `GET /api/targets/{id}/profile` returns total runs, counts by family and by verdict, and recent one-line summaries newest first; an unused target returns zeros and an empty list, not an error; a missing target returns 404; no auth value, URL or name appears.

### Implementation

- [ ] T030 [US4] Add a `profile(target_id)` aggregation to `src/kestrel/experience/store.py` (read memory via `get(where type=memory, target_id)`; the `recent` list capped at **10** summaries, newest first; U1), a `ProfileOut` schema in `src/kestrel/api/schemas.py`, and `GET /api/targets/{id}/profile` in `src/kestrel/api/main.py`. (makes T029 pass)

**Checkpoint**: a user can read a target's history.

---

## Phase 7: User Story 5 — Forget a target when it is deleted (Priority: P3)

**Goal**: deleting a target deletes its memory; shared patterns survive.

**Independent Test**: delete a target that has memory and a success-derived pattern; its memory is gone, the pattern remains.

### Tests (write first, must fail)

- [ ] T031 [P] [US5] Write `tests/integration/test_delete_clears_memory.py` (FR-024, FR-025, SC-010): deleting a target removes all of its memory records and leaves shared patterns intact; a later warm attack on another target retrieves none of the deleted target's memory.

### Implementation

- [ ] T032 [US5] Add `delete_target_memory(target_id)` to `src/kestrel/experience/store.py` (`delete(where type=memory, target_id)`) and call it from the `DELETE /api/targets/{id}` handler in `src/kestrel/api/main.py` after `store.delete_target`. (makes T031 pass)

**Checkpoint**: deletion is complete across both stores.

---

## Phase 8: Screen (US1–US4 surfaces, one file)

**Goal**: the experience toggle, the purpose field, the profile view, and the write-back warning — all in `ui/app.py`, tested with `AppTest` and a stubbed `api_client`.

### Tests (write first, must fail)

- [ ] T033 [P] Write `tests/integration/test_ui_experience.py` (FR-010, FR-014, FR-020, FR-022, SC-007/SC-013 screen side): the Attack panel shows a "Use prior experience" toggle defaulting to on; the target form has the one-line purpose field marked "no sensitive info"; a finished run with `memory_written=false` shows a visible warning; the profile section renders counts by family and verdict and recent summaries; secrets never appear.

### Implementation

- [ ] T034 Implement the screen in `ui/app.py` and `ui/api_client.py`: the experience toggle (sends `use_prior_experience`), the purpose field (sends `description`), the profile section (`get_profile`), and the write-back warning; add `get_profile` and pass `description`/`use_prior_experience` in `ui/api_client.py`. (makes T033 pass)

**Checkpoint**: the whole feature is usable from the screen.

---

## Phase 9: End-to-end & polish

- [ ] T035 [US2] Write `tests/e2e/test_us2_experience.py` (FR-026, FR-027, SC-012): two warm adaptive runs against the sacrificial HS-code target (started/stopped by the test, reused unchanged), asserting the second run's attacker — a spy wrapping the real attacker — receives at least one memory record produced by the first run. Ensure run 2 reaches a turn where the attacker actually generates (turn ≥2; the HS target holds, so with the e2e turn cap it will — the hint is delivered on the attacker's first generation, not the seed turn; A1). Set `KESTREL_CHROMA_PATH` to a temp dir in the e2e `kestrel_api` env so the store is isolated and the default embedding model downloads once into the cache, not into `data/chroma` (G1).
- [ ] T036 [P] Update the root `README.md`: the experience store and per-target memory, the new env vars (`KESTREL_CHROMA_PATH`, `KESTREL_EXPERIENCE_PATTERN_K`, `KESTREL_EXPERIENCE_MEMORY_CAP`), the warm-by-default switch, and that the first e2e run downloads ChromaDB's default embedding model once.
- [ ] T037 Secret-hygiene audit across `src/kestrel/experience/**`, the hint path (`attack/attacker.py`, `attack/graph.py`) and write-back (FR-005, FR-011, FR-012, SC-004, SC-008): confirm no target URL, display name or auth value can reach a pattern/memory record, a hint, a log line, or the profile, and that no memory document holds a raw target reply.
- [ ] T038 Run the full suite and the quickstart checks: `uv run pytest`, `uv run pytest -m e2e`, `uv run --directory targets/hs_code pytest`; fix any difference.

---

## Dependencies & execution order

- **Setup (P1)** → **Foundational (P2)** blocks everything.
- **US1 (P3)** is the MVP and must land before US2/US4/US5 can be meaningfully tested (they read what US1 writes); US3 depends only on Foundational (the `description` column) but its "fed to the attacker" leg (T028) rides on US2's `hint_provider`.
- **Screen (P8)** depends on the API surfaces of US1–US4.
- **E2E (T035)** depends on US1 + US2.
- Within a story: tests first and must fail; store methods before the API wiring; API before the screen.

## Parallel opportunities

- Setup: T002 ‖ (T001 first — it creates the package).
- Foundational tests T003 ‖ T004 ‖ T005 (different files); then implementation T006/T007/T008 (T006 and T007 different files, can be parallel; T008 independent).
- Within each story the `[P]` tests are different files and run together; the implementation tasks that touch `api/main.py` or `schemas.py` are **sequential** (same files: T015, T024, T027, T028, T030, T032 all edit `api/main.py`).
- `ui/app.py` tasks are sequential (one file).

## Implementation strategy

1. Setup + Foundational.
2. **US1 (MVP)** → validate: every run writes back, failures are loud. This alone closes Principle V.
3. US2 → warm/cold retrieval; US3 → purpose; US4 → profile; US5 → deletion.
4. Screen, then e2e and polish.

## Requirement coverage

| FR | Tasks | | FR | Tasks |
|---|---|---|---|---|
| FR-001 | T005, T008 | | FR-015 | T019, T024 |
| FR-002 | T005, T008 | | FR-016 | T016, T019, T020, T024 |
| FR-003 | T003, T005, T006, T008 | | FR-017 | T016, T020 |
| FR-004 | T010, T012, T015 | | FR-018 | T016, T020 |
| FR-005 | T010, T012, T037 | | FR-019 | T017, T018, T021, T022 |
| FR-006 | T011, T014 | | FR-020 | T025, T027, T033, T034 |
| FR-007 | T011, T012, T014 | | FR-021 | T026, T028 |
| FR-008 | T009, T013 | | FR-022 | T029, T030, T033, T034 |
| FR-009 | T011, T012, T014 | | FR-023 | T029, T030 |
| FR-010 | T011, T014, T015, T033 | | FR-024 | T031, T032 |
| FR-011 | T011, T037 | | FR-025 | T031, T032 |
| FR-012 | T011, T037 | | FR-026 | T035 |
| FR-013 | T009, T013 | | FR-027 | T035 |
| FR-014 | T019, T024 | | | |

| SC | Tasks | | SC | Tasks |
|---|---|---|---|---|
| SC-001 | T011 | | SC-008 | T011, T037 |
| SC-002 | T010 | | SC-009 | T009, T013 |
| SC-003 | T011 | | SC-010 | T031 |
| SC-004 | T011, T037 | | SC-011 | T011, T014 |
| SC-005 | T019, T035 | | SC-012 | T035 |
| SC-006 | T016 | | SC-013 | T029, T033 |
| SC-007 | T017, T018, T019 | | SC-014 | T016 |
