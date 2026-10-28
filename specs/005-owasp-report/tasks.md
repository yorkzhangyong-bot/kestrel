---

description: "Task list for feature 005: OWASP-mapped, fix-ready report"
---

# Tasks: OWASP-Mapped, Fix-Ready Report

**Input**: Design documents in `/specs/005-owasp-report/` (plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md)

**Tests**: included and written first (Constitution Principle VII). No test, fixture, comment or commit contains attack prompt text — behaviour only.

**Organization**: by user story. US1 (generate + deliver) is the MVP; later stories add the findings, the coverage table, and the safety guarantees.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: can run in parallel (different file, no dependency on an unfinished task)
- **[Story]**: US1–US4; Setup/Foundational/Polish carry no story label

## Path conventions

Single repo: `src/kestrel/`, `ui/`, `tests/` at the root; the sacrificial target under `targets/hs_code/` (reused unchanged).

---

## Phase 1: Setup

- [X] T001 Add `markdown-it-py` to `[project].dependencies` in `pyproject.toml` (one-line note: derive escaped HTML from the report Markdown, Principle X) and run `uv sync`; create the package `src/kestrel/report/__init__.py`.

---

## Phase 2: Foundational (blocking prerequisites)

- [X] T002 Define the report data structures in `src/kestrel/report/model.py` — `ReportModel`, `Header`, `CoverageRow`, `Finding`, `OtherRun`, `Recommendation` dataclasses (the shared contract every story populates). Plain data, no I/O.

**Checkpoint**: the report model exists; the stories can build and render it.

---

## Phase 3: User Story 1 — Generate a report and read it (Priority: P1) 🎯 MVP

**Goal**: generate a report for a target (header, failed/unclear runs, limitations), preview it, and download it as Markdown or HTML; a target with no runs shows a clear empty state.

**Independent Test**: with a target that has runs, generate a report and confirm the preview and both downloads show the header, the failed/unclear list and the limitations note; a target with no runs shows the empty state.

### Tests (write first, must fail)

- [X] T003 [P] [US1] Write `tests/unit/test_report_render.py` (FR-001, FR-005, FR-014, FR-015, FR-019, SC-001, SC-010): `render_markdown` produces the sections it has, in order (header with name/purpose/time/run count/attacker+judge models/token budget+used; failed-unclear lines; limitations), with all run-derived content inside fenced code blocks; an empty model renders only the empty-state message.
- [X] T004 [P] [US1] Write `tests/unit/test_report_html.py` (FR-017, SC-008): `render_html` derives HTML from the Markdown, escapes run-derived HTML/script so it shows as text, and is self-contained (no external CSS/JS/image references).
- [X] T005 [P] [US1] Write `tests/integration/test_report_endpoint.py` (FR-002, FR-003, FR-019, SC-001, SC-009): `GET /api/targets/{id}/report?format=md` and `?format=html` return 200 with the right content type; a bad `format` returns 422; a missing target returns 404; a target with no runs returns 200 empty-state with 0 judge calls.

### Implementation

- [X] T006 [US1] Implement `build_report(...)` in `src/kestrel/report/model.py` for the header, the failed/unclear `other_runs` (one line each), the limitations note, and `is_empty` — a pure function over target/runs/turns. The header lists only the models actually present across the runs (single-turn runs have no attacker model — A1). (makes T003 pass)
- [X] T007 [US1] Implement `render_markdown(model)` in `src/kestrel/report/render.py` — one template, sections in order, run-derived content fenced. (makes T003 pass)
- [X] T008 [US1] Implement `render_html(markdown)` in `src/kestrel/report/render.py` using `markdown-it-py` (`html=False`) wrapped in a minimal self-contained HTML document. (makes T004 pass)
- [X] T009 [US1] Add `GET /api/targets/{id}/report` in `src/kestrel/api/main.py`: validate `format` (md/html, else 422), 404 on missing target, load runs/turns, build + render, return the body with the right media type; empty target → empty-state body, no judge call. (makes T005 pass)
- [X] T010 [US1] Add the Report section in `ui/app.py` after `render_profile()` (Generate report, preview via `st.markdown(..., unsafe_allow_html=False)`, Markdown + HTML download buttons) and `get_report(target_id, fmt)` in `ui/api_client.py`.

**Checkpoint**: a report can be generated, previewed and downloaded in both formats.

---

## Phase 4: User Story 2 — Findings and recommendations (Priority: P2)

**Goal**: one finding per successful run — family, OWASP class, winning attacker message, verbatim hard evidence or the judge's note (suspected), and a model-generated, suggestion-marked recommendation cached per run.

**Independent Test**: with a canary success and a judge-only success, confirm each produces one finding whose evidence is quoted verbatim or shown as the judge's note, whose recommendation is labelled a suggestion, and that a second report generation makes no new judge call.

### Tests (write first, must fail)

- [ ] T011 [P] [US2] Write `tests/unit/test_report_findings.py` (FR-009, FR-010, FR-011, SC-002, SC-003): `build_report` yields exactly one finding per "succeeded" run and none for other runs; a canary success quotes the stored evidence byte-for-byte; a judge-only success shows the note marked suspected; the winning message is the attacker turn(s) up to `succeeded_turn` (or the seed for a single-turn/turn-one success).
- [ ] T012 [P] [US2] Write `tests/unit/test_judge_recommend.py` (FR-018): `JudgeClient.recommend(...)` posts only non-secret fields (family, OWASP class, winning message, evidence) and returns text + tokens via `httpx.MockTransport`; raises `JudgeError` when not configured.
- [ ] T013 [P] [US2] Write `tests/unit/test_store_migration_v5.py`: a fresh database is at version 5 with a `report_recommendations` table; a version-4 database migrates to 5 keeping its rows; `get_recommendation`/`save_recommendation` round-trip; an unknown version is refused.
- [ ] T014 [P] [US2] Write `tests/integration/test_report_recommendations.py` (FR-012, FR-013, SC-004, SC-011): a generated report fills a suggestion-marked recommendation for each success (stub judge); regenerating makes 0 new judge calls (served from the cache); with no judge key, findings show a clear "no recommendation available" note and 0 judge calls.

### Implementation

- [ ] T015 [US2] Extend `src/kestrel/store.py` to schema v5: add the `report_recommendations` table, allow migration from `1`/`2`/`3`/`4` → `5`, and add `get_recommendation`/`save_recommendation`. (makes T013 pass)
- [ ] T016 [US2] Add `JudgeClient.recommend(...)` in `src/kestrel/judge/client.py`, reusing the client's model/key/base-url/transport, with a fix-advice system prompt and non-secret inputs. (makes T012 pass)
- [ ] T017 [US2] Implement `src/kestrel/report/recommend.py` `recommendations_for(store, judge, runs, turns_by_run)`: return cached recommendations, call the judge once per uncached success, save each; skip when no judge key. (makes part of T014)
- [ ] T018 [US2] Populate `findings` in `build_report` (winning message, verbatim evidence / judge note, recommendation), render them in `render_markdown` (fenced content; recommendation under a "Suggestion" label), and call `recommendations_for` from the endpoint in `src/kestrel/api/main.py`. (makes T011, T014 pass)

**Checkpoint**: successful runs appear as fix-ready findings with cached recommendations.

---

## Phase 5: User Story 3 — Honest OWASP coverage (Priority: P2)

**Goal**: a coverage table of the three tested OWASP classes mapped to families with run counts and results ("not run yet" where none), plus an honest list of the seven untested classes with reasons.

**Independent Test**: with runs in some families but not others, the coverage table shows counts/results and "not run yet" correctly, and the report lists the seven untested classes each with a reason.

### Tests (write first, must fail)

- [ ] T019 [P] [US3] Write `tests/unit/test_report_coverage.py` (FR-006, FR-007, FR-008, SC-005): the coverage table lists exactly the three tested classes (LLM01 Prompt Injection → direct & indirect injection; LLM06 Excessive Agency → tool-mediated exfiltration; LLM07 System Prompt Leakage → system-prompt leak) with per-class run counts and results, "not run yet" for a family with 0 runs; the untested section lists exactly the seven classes (LLM02, LLM03, LLM04, LLM05, LLM08, LLM09, LLM10), each with a reason.

### Implementation

- [ ] T020 [US3] Add `src/kestrel/report/owasp.py`: the OWASP LLM Top 10 (2025) data — the three tested classes and their families, and the seven untested classes each with a short reason. (makes part of T019)
- [ ] T021 [US3] Add the coverage rows and the untested-classes section to `build_report` (`src/kestrel/report/model.py`) and to `render_markdown` (`src/kestrel/report/render.py`). (makes T019 pass)

**Checkpoint**: the report states honestly what was and was not tested.

---

## Phase 6: User Story 4 — Safe, read-only reporting (Priority: P3)

**Goal**: generating a report starts no attack, sends nothing to the target, writes nothing to the experience store, and leaks no URL/headers/secrets; the experience store is read only for the memory/pattern counts in the limitations note.

**Independent Test**: generate a report and confirm 0 requests reach the target, 0 writes hit the experience store, and a known auth value, the target URL and header names appear nowhere in either format.

### Tests (write first, must fail)

- [ ] T022 [P] [US4] Write `tests/integration/test_report_safety.py` (FR-003, FR-016, FR-018, SC-006, SC-007): generating a report makes 0 sends through the target transport and 0 writes to the experience store (spy), and neither the Markdown nor the HTML output contains the target's auth value, URL, or header names.

### Implementation

- [ ] T023 [US4] Confirm the endpoint's invariants in `src/kestrel/api/main.py`: recommendation input carries no secret (FR-018), the experience store is read only (counts via `count(...)` for the limitations note, no write), and the memory/pattern counts are folded into the limitations note (FR-015). (makes T022 pass)

**Checkpoint**: the report is safe to generate and share.

---

## Phase 7: Polish

- [ ] T024 [P] Update the root `README.md` (and the `docs/technical-design.md` roadmap line) for the report: the Report section, the `GET /api/targets/{id}/report` endpoint, the `markdown-it-py` dependency, and schema v5.
- [ ] T025 Secret-hygiene audit across `src/kestrel/report/**`, the report endpoint, and `JudgeClient.recommend` (FR-016, FR-018, SC-006): confirm no target URL, header name/value or secret reaches the report output, the recommendation prompt, or a log line.
- [ ] T026 Run the full suite: `uv run pytest`, `uv run --directory targets/hs_code pytest`, and `uv run pytest -m e2e`; fix any difference.
- [ ] T027 [US1] Write `tests/e2e/test_report_e2e.py` (Principle VII, required): run one attack against the sacrificial target (isolated temp DB and `KESTREL_CHROMA_PATH`), generate the report in both Markdown and HTML, and assert the run appears in the OWASP coverage table and that the experience-store record count is unchanged by report generation (read-only).

---

## Dependencies & execution order

- **Setup (P1)** → **Foundational (P2)** blocks everything.
- **US1 (P3)** is the MVP and establishes `build_report` + the renderers + the endpoint + the UI; **US2**, **US3** extend the same `model.py`, `render.py` and the endpoint, so their implementation tasks are sequential with US1's and each other (same files). **US2's** schema change (T015) and `judge.recommend` (T016) are independent of US1.
- **US4** verifies invariants over the finished endpoint; its one impl task tightens wiring.
- Within a story: tests first and must fail; the pure model/renderers before the API wiring; the API before the screen.

## Parallel opportunities

- Setup: T001 first (creates the package).
- Each story's `[P]` tests are different files and run together (e.g. T003 ‖ T004 ‖ T005; T011 ‖ T012 ‖ T013 ‖ T014).
- Implementation tasks that touch `report/model.py`, `report/render.py` or `api/main.py` are **sequential** across stories (T006/T007/T018/T021 on the pure modules; T009/T018/T023 on `api/main.py`).
- `ui/app.py` is one file (T010 sequential).

## Implementation strategy

1. Setup + Foundational.
2. **US1 (MVP)** → a generatable, downloadable report (header, failed/unclear, limitations, empty state).
3. US2 → findings + cached recommendations; US3 → the coverage table + untested list; US4 → safety guarantees.
4. Polish: docs, audit, full-suite run, and the required e2e (T027).

## Requirement coverage

| FR | Tasks | | FR | Tasks |
|---|---|---|---|---|
| FR-001 | T003, T007, T010 | | FR-011 | T011, T018 |
| FR-002 | T005, T009, T027 | | FR-012 | T014, T017, T018 |
| FR-003 | T009, T022 | | FR-013 | T014, T017 |
| FR-004 | T009 | | FR-014 | T003, T006 |
| FR-005 | T003, T006 | | FR-015 | T006, T023 |
| FR-006 | T019, T020, T021 | | FR-016 | T022, T025 |
| FR-007 | T019, T021 | | FR-017 | T004, T008 |
| FR-008 | T019, T020, T021 | | FR-018 | T012, T016, T025 |
| FR-009 | T011, T018 | | FR-019 | T005, T006, T009 |
| FR-010 | T011, T018 | | | |

| SC | Tasks | | SC | Tasks |
|---|---|---|---|---|
| SC-001 | T003, T005, T007 | | SC-007 | T022 |
| SC-002 | T011 | | SC-008 | T004, T008 |
| SC-003 | T011 | | SC-009 | T005 |
| SC-004 | T014 | | SC-010 | T003, T006 |
| SC-005 | T019 | | SC-011 | T014, T017 |
| SC-006 | T022, T025 | | | |
