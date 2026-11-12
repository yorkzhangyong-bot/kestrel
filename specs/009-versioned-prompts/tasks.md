---

description: "Task list for feature 009 — versioned prompts"
---

# Tasks: Versioned Prompts (009)

**Input**: Design documents from `specs/009-versioned-prompts/` (plan.md, spec.md, research.md, data-model.md, contracts/)

**Tests**: REQUIRED — Principle VII (tests-first, one e2e per feature). Every test carries a traceability token
`009/FR-###` / `009/SC-###` (or module-level `FEATURE = "009"`).

**Organization**: by user story. MVP = Setup + Foundational + US1 + US2 (both P1). US3–US5 are P2 increments.

**Registry note**: three prompt kinds only (`attacker:<family>`, `judge`, `recommender`) — the memory summariser is
deterministic, no prompt (see spec Assumptions footnote + research D5).

## Phase 1: Setup

- [X] T001 Create module scaffold `src/kestrel/prompt_registry.py` and committed placeholder `src/kestrel/prompt_versions.lock.json` so later tests can import.

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ Blocks every user story.**

- [X] T002 Implement the registry core in `src/kestrel/prompt_registry.py`: `PromptEntry`, `fingerprint()` (stdlib `hashlib.sha256`), `is_valid_version()` (stdlib `re`), `registry()` enumerating `attacker:<family>` (from `attack/attacker.py` `SYSTEM_PROMPT`+`GOALS`), `judge`, `recommender` (`judge/client.py`) with active version from the lock, plus `has()` and `text_for(id, version)`. No new dependency (009/FR-001).
- [X] T003 Seed `src/kestrel/prompt_versions.lock.json` with the three ids at `1.0.0` and their current fingerprints (009/FR-002).
- [X] T004 Schema v7 migration in `src/kestrel/store.py`: add nullable columns `run_turns.{attacker_prompt_id,attacker_prompt_version,judge_prompt_id,judge_prompt_version}`, `runs.{judge_prompt_id,judge_prompt_version}`, `experiment_arms.{prompt_arm_target,prompt_arm_version}`; extend accepted prior versions to include `"6"`; bump `SCHEMA_VERSION` to `"7"` via the ALTER-tuple mechanism (009/FR-004).

**Checkpoint**: registry + lock + schema ready — stories can begin.

---

## Phase 3: User Story 1 — Know which prompt produced a result (P1) 🎯 MVP

**Goal**: every adaptive run turn and judge verdict records the prompt id+version that produced it.
**Independent Test**: run an adaptive attack + verdict; assert each `run_turns`/`runs` row carries the id+version at `1.0.0`; a pre-v7 row reads "not recorded".

- [X] T005 [P] [US1] Unit test `tests/unit/test_prompt_registry.py` — `registry()` yields the three kinds at `1.0.0`; `has()`/`text_for()` resolve; versions validate (009/FR-001, 009/FR-002).
- [X] T006 [P] [US1] Integration test `tests/integration/test_provenance_recorded.py` — stub-target adaptive run records attacker+judge id/version on each `run_turns` row and judge id/version on the `runs` verdict (009/FR-003, 009/SC-001).
- [X] T007 [P] [US1] Integration test `tests/integration/test_provenance_migration.py` — a v6 DB migrates to v7; pre-existing rows read back the NULL "not recorded" marker (009/FR-004).
- [X] T008 [P] [US1] `src/kestrel/attack/attacker.py` — resolve the active `attacker:<family>` id+version from the registry and expose it with each produced turn (009/FR-003).
- [X] T009 [P] [US1] `src/kestrel/judge/client.py` — resolve the active `judge` id+version and expose it with each verdict (009/FR-003).
- [X] T010 [US1] `src/kestrel/store.py` — `add_turn()` records attacker+judge provenance on `run_turns`; `finish_run()` records judge provenance on `runs`; read paths surface NULL as "not recorded" (009/FR-003, 009/FR-004).
- [X] T011 [US1] `src/kestrel/attack/` adaptive loop — thread the attacker/judge provenance into `add_turn`/`finish_run` (009/FR-003).

**Checkpoint**: provenance recorded end to end.

---

## Phase 4: User Story 2 — A prompt cannot change silently (P1) 🎯 MVP

**Goal**: editing a prompt's authored text without a version bump fails the suite and names the prompt.
**Independent Test**: edit one char of a prompt without touching the lock → guard test fails naming it; revert/bump → green.

- [X] T012 [P] [US2] `tests/unit/test_prompt_guard.py` — assert `verify_lock() == []` on shipped prompts (the live CI guard); a stubbed text change makes `verify_lock()` name the changed id; two texts for one id+version is rejected. Write FIRST; fails until T013 (009/FR-005, 009/FR-006, 009/SC-002).
- [X] T013 [US2] `src/kestrel/prompt_registry.py` — implement `verify_lock()` (each live fingerprint vs the lock's active entry → mismatched ids) and the one-id-one-text rule (009/FR-005, 009/FR-006).

**Checkpoint**: silent prompt drift is caught.

---

## Phase 5: User Story 3 — See the active prompt versions (P2)

**Goal**: active versions exposed on `/api/config` and shown in the UI; no raw text.
**Independent Test**: `curl /api/config` lists `{id,version}` per prompt; UI shows the same; no text on either.

- [X] T014 [P] [US3] Integration test `tests/integration/test_config_prompts.py` — `GET /api/config` returns `prompts:[{id,version}]` for the three kinds, no text (009/FR-007, 009/SC-004).
- [X] T015 [P] [US3] UI test `tests/integration/test_ui_prompt_versions.py` — the UI shows active prompt versions from `/api/config`, no raw text (009/FR-007, 009/SC-004).
- [X] T016 [US3] `src/kestrel/api/schemas.py` — add `PromptVersionOut` and `ConfigOut.prompts` (009/FR-007).
- [X] T017 [US3] `src/kestrel/api/main.py` — `get_config()` populates `prompts` from `registry()`, no secrets (009/FR-007, 009/FR-012).
- [X] T018 [US3] `ui/app.py` — display active prompt versions from `config["prompts"]` (UI holds no logic) (009/FR-007).

**Checkpoint**: versions visible via API + UI.

---

## Phase 6: User Story 4 — A/B test two versions of a prompt (P2)

**Goal**: a 007 prompt-version arm for the attacker/judge prompts; the diff names the prompt + both versions.
**Independent Test**: a 2-arm experiment differing only by a judge prompt version runs and produces the comparison; recommender/absent targets are refused pre-run.

- [X] T019 [P] [US4] Integration test `tests/integration/test_prompt_arm.py` — two arms differing only by `prompt_arm_target=judge`/`prompt_arm_version` validate as distinct and the diff names the prompt + both versions; a `recommender` target and a registry-absent `(target,version)` are refused before any model call (009/FR-008, 009/FR-009, 009/SC-005).
- [X] T020 [US4] `src/kestrel/store.py` — add `prompt_arm_target`/`prompt_arm_version` to `ExperimentArm` and `create_experiment` persistence (columns from T004) (009/FR-008).
- [X] T021 [US4] `src/kestrel/api/schemas.py` — add the two fields to `ARM_DIFF_FIELDS`; `validate_experiment` accepts a prompt-version-only difference and refuses non-attacker/judge targets or registry-absent `(target,version)`; `experiment_diff` renders `prompt: A=…@…, B=…@…` (009/FR-008, 009/FR-009).
- [X] T022 [US4] `src/kestrel/experiments/engine.py` (+ `attack/attacker.py`, `judge/client.py`) — an arm pins its prompt to `text_for(target, version)` for its runs (009/FR-008).

**Checkpoint**: prompt-version A/B works with the existing stats.

---

## Phase 7: User Story 5 — Judge accuracy per prompt version (P2)

**Goal**: the judge eval reports results grouped by judge prompt version.
**Independent Test**: `uv run pytest -m judge_eval` prints metrics under `judge_prompt_version=<v>`.

- [X] T023 [US5] `tests/eval/test_judge_accuracy.py` — resolve the active `judge` prompt version from the registry, group/print metrics under `judge_prompt_version=<v>`, keep the `recall >= 0.80` floor (no drift at `1.0.0`) (009/FR-010, 009/SC-006, 009/SC-003).

**Checkpoint**: eval names/groups by judge prompt version.

---

## Phase 8: Polish & Cross-Cutting

- [X] T024 [P] Security test `tests/integration/test_prompt_no_secrets.py` — `registry()`, the lock, and `/api/config` carry no target auth value/URL/name and no attack-library fixture text (009/FR-011, 009/FR-012, 009/SC-007).
- [X] T025 [P] e2e `tests/e2e/test_prompt_provenance_e2e.py` — one e2e against the HS-code target: a real adaptive run records provenance (marker `e2e`, Principle VII) (009/SC-001).
- [X] T026 [P] Docs — update `docs/technical-design.md` (registry + schema v7) and add a dated learned note to `CLAUDE.md`.
- [X] T027 Quality gate — `uv run ruff check src ui tests`; mypy advisory on `src`; `uv run pytest tests/unit tests/integration` coverage ≥85%; run `quickstart.md`, incl. "no behaviour drift by default" (009/FR-013, 009/SC-003).
- [X] T028 Traceability — confirm every new test carries a `009/FR-###`/`009/SC-###` token or `FEATURE="009"`; record any untraced ids in `specs/009-versioned-prompts/traceability.md`.

---

## Dependencies & Execution Order

- **Setup (T001)** → **Foundational (T002–T004)** blocks all stories. T002 before T003 (lock seeded from registry) before/with T004 (independent file).
- **US1 (T005–T011)** and **US2 (T012–T013)** depend only on Foundational; both are P1 (the MVP). US2 needs only the registry (T002–T003), not the schema.
- **US3 (T014–T018)**, **US4 (T019–T022)**, **US5 (T023)** depend on Foundational; US4 also needs the v7 arm columns (T004).
- **Polish (T024–T028)** after the stories it checks; T028 last.
- Within a story: tests (T005–T007, T012, T014–T015, T019) are written FIRST and must fail before their implementation.
- Same-file ordering (not parallel): `store.py` T004 → T010 → T020; `schemas.py` T016 → T021; `attacker.py`/`judge/client.py` T008/T009 → T022.

## Parallel Opportunities

- US1 tests T005, T006, T007 together; impl T008 and T009 together (different files).
- US3 tests T014, T015 together. Polish T024, T025, T026 together.
- After Foundational, US1/US2 can proceed in parallel with US3/US5 (US4 waits on nothing extra beyond T004).

## Implementation Strategy

1. Setup + Foundational (T001–T004) → foundation ready.
2. US1 + US2 (T005–T013) → **MVP**: provenance recorded and un-changeable-without-a-bump. Stop & validate.
3. US3 (visibility), US5 (eval-per-version), US4 (A/B arm) as independent P2 increments.
4. Polish: security test, e2e, docs, quality gate, traceability.

## Notes

- Tests cite the feature per the project rule (`009/FR-###` scoped token or `FEATURE = "009"`); untraced ids go in `specs/009-versioned-prompts/traceability.md`.
- No new runtime dependency (Principle X): `hashlib`/`re` are stdlib; schema step is the additive `6 → 7` migration.
- Secrets never leave the vault: the registry/lock/config carry only ids, versions, fingerprints, and the prompts' own authored text (009/FR-011, 009/FR-012).
