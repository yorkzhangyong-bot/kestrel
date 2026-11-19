# Implementation Plan: Retrieval Controls for the Experience Store (011)

**Branch**: `011-retrieval-controls` | **Date**: 2026-11-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/011-retrieval-controls/spec.md`

## Summary

Make the experience store's pattern retrieval safe and selective, and its success write-back cumulative, without
leaving the fixed stack. One new module, `src/kestrel/experience/retrieval.py`, builds the retrieval query from the
family label and the attacker's **last two own messages** (the `attacker` role only — never the target's reply, the
judge's reason or its progress note), fetches a bounded candidate pool from the family-scoped collection with the
collection's own distances and embeddings, and selects nearest first under a **distance floor** (`1.8`, pinned
from real-model measurements that include queries without the seed) and a **near-identical threshold** (`0.15`),
both settings with an `off` value and both on by default; the one factory
`background_provider(...)` replaces the two divergent hint providers of the API and the experiment engine. The
success write-back looks up the nearest same-family pattern and, within the same threshold, **raises its
`hit_count`** (library seeds eligible) instead of adding a copy — amending, on purpose, feature 004's "no
de-duplication" clause and the one existing test that relied on it. The collection is created with an explicit
**`l2` distance space** and its metadata records the **embedding model name** (`all-MiniLM-L6-v2` for the shipped
default) and the space (both stamped onto feature-004 stores on first open); `self_check` turns a mismatch of
either into `EmbeddingModelMismatch` / `SpaceMismatch` → the feature-010 `experience.unavailable` path with
`reason_kind = embedding_model_mismatch` / `space_mismatch`, both values as fields, a mismatch-specific constant
message that states the remedy, and a store disabled for the session. The settings and the
outcome counts ride on the existing `memory.retrieval` line, the merge/add outcome on `memory.writeback` (catalogue
and the 010 contract extended; `spec-change:` note on the PR). The offline proof runs on a re-implemented
**lexical** test embedding (hashed bag of words, normalised) and a labelled **recall@k fixture**; one end-to-end run
confirms the shipped numbers on the real model. Last task: the roadmap moves "Retrieval controls" to Done as 011
and renumbers 012–014.

Approach and rationale: [research.md](research.md) (D1–D13, with the real-model measurements the defaults come
from); shapes: [data-model.md](data-model.md) and [contracts/](contracts/); validation: [quickstart.md](quickstart.md).

## Technical Context

**Language/Version**: Python 3.12 (uv-managed), unchanged.

**Primary Dependencies**: FastAPI, Streamlit, LangGraph, httpx, ChromaDB 1.5.9, markdown-it-py — all existing.
The floor and the de-duplication use the collection's reported `l2` distances and its stored embeddings with the
standard library (`math`, `zlib.crc32` in the test stub); **no new dependency, required or optional**
(Principle X, FR-016).

**Storage**: ChromaDB collection `kestrel_experience` (created with an explicit `l2` space; metadata gains
`kestrel_embedding_model` and `kestrel_distance_space`; pattern metadata gains `hit_count` and `last_hit_run_id`)
— no re-embedding, no migration beyond the first-open stamp (feature-004 stores are `l2` already). SQLite schema:
planned to stay at v8; the owner-approved fix after the independent review moved it to **v9**, rebuilding `runs`
with `AUTOINCREMENT` so a run id is never reissued, and gave each added pattern a unique `pattern:run:<uuid>` id
(data-model.md).

**Testing**: pytest; unit + integration offline with the lexical stub embedding and temporary stores (never
`data/chroma`); one `e2e` against the HS-code target with the real model. Tests first (Principle VII); every test
carries `011/FR-###` / `011/SC-###` or a module-level `FEATURE = "011"`.

**Target Platform**: local/hosted FastAPI service + Streamlit UI (Windows 11 dev; PowerShell).

**Project Type**: web service (FastAPI API) + Streamlit UI that only calls the API (the UI is untouched here; the
config endpoint gains two fields).

**Performance Goals**: per warm adaptive turn, one family-scoped `count` + one `query` of at most `4k` results
(k = 5 → 20) with embeddings included, plus at most `k × 20` squared-distance sums over 384-dimensional vectors in
Python (microseconds); per success write-back, one extra `query` of one result and one metadata `update`. All
local; the run's caps and timings are unaffected.

**Constraints**: nothing from the target (reply text) or the judge (reason, progress) in the query — enforced by
role filtering in one shared builder (FR-001/FR-002); no text on any log line (`010/FR-009`); the controls never
change a verdict, a cap or the permission gate (FR-015); existing feature-004 stores keep working (FR-011);
feature-007 arms keep their meaning; the offline suite stays offline (D8); no attack wording in the fixture.

**Scale/Scope**: single user; the pool grows by at most one pattern per success and now by fewer (merges);
candidate pools of at most 20; a few hundred patterns at most.

## Constitution Check

*GATE: must pass before Phase 0 and after Phase 1. Result: **PASS** — no violations.*

| Principle | Assessment |
|-----------|------------|
| I — security not quality | Retrieval quality serves the attack's effectiveness and removes a target-controlled input from Kestrel's own path; no quality metric of the target is introduced. ✓ |
| II — hard evidence over opinion | Untouched: a canary still decides a run; patterns are hints, never evidence; hit counts never change a verdict. ✓ |
| III — report states attacker model | Unchanged; the memory record still carries the attacker model. ✓ |
| IV — secrets never leave the vault | No URL, name or auth value reaches the store, its metadata, the query or a line (FR-017); the new line fields are numbers, ids and model names; the exception naming the models never reaches a line (`exc_type` only). ✓ |
| V — learn from every run | Every run still writes its memory record; a success still writes back — now as a merge or an add, both loud on the line; a failed look-up fails the write-back loudly as today. ✓ |
| VI — OWASP-mapped, fix-ready | Pattern and memory metadata keep family and OWASP category. ✓ |
| VII — tests first, thin slices, one e2e | TDD per story; vertical slice store → retrieval → API/engine → lines; one e2e (`tests/e2e/test_us011_retrieval.py`). ✓ |
| VIII — only attack owned, hard caps | Caps, permission box, token budget untouched; retrieval adds no model call and no target request (FR-015). ✓ |
| IX — simple for a vibe coder | Nothing new to configure: both controls on with sane defaults; two optional settings with an `off` value; a mismatch is one clear line with the remedy. ✓ |
| X — stack fixed; new dep needs justification | **No new dependency**: ChromaDB's own distances and embeddings, standard library arithmetic. ✓ |

Complexity Tracking: none required.

## Project Structure

### Documentation (this feature)

```text
specs/011-retrieval-controls/
├── plan.md              # this file
├── research.md          # Phase 0 — decisions D1–D13 and the real-model measurements
├── data-model.md        # Phase 1 — collection metadata, pattern fields, value types, settings, line fields, fixture
├── contracts/           # Phase 1 — experience-store.md, retrieval.md, log-records-delta.md, recall-fixture.md
├── quickstart.md        # Phase 1 — US1–US5 validation, the manual mismatch check, the e2e
├── checklists/requirements.md
├── spec.md
└── tasks.md             # Phase 2 — /speckit-tasks
```

### Source code (files this feature touches)

```text
.env.example                         # KESTREL_EXPERIENCE_DISTANCE_FLOOR, KESTREL_EXPERIENCE_DEDUPE_THRESHOLD (+ "off", retune note)
src/kestrel/
├── experience/retrieval.py          # NEW — QUERY_MESSAGES, CANDIDATE_MULTIPLIER, Selection, build_query, select_patterns, background_provider (imports Candidate from store.py)
├── experience/store.py              # Candidate, PatternWrite, EmbeddingModelMismatch, SpaceMismatch; EMBEDDING_MODEL_KEY, DISTANCE_SPACE_KEY, embedding_model_name; explicit l2 configuration at creation, actual space read back; embedding_model= ctor arg, stamp on open, self_check compares space then model; seed_patterns keeps hit_count; query_patterns; write_pattern(dedupe_threshold) -> PatternWrite; store_error_kind
├── experience/writeback.py          # write_back(..., dedupe_threshold=None); outcome fields on memory.writeback
├── events.py                        # CATALOGUE: memory.retrieval, memory.writeback, experience.unavailable fields; memory_retrieval/memory_writeback keyword arguments
├── settings.py                      # experience_distance_floor, experience_dedupe_threshold; non_negative_float_or_off; RetrievalSettings + Settings.retrieval
├── api/schemas.py                   # ExperienceOut: distance_floor, dedupe_threshold
├── api/main.py                      # background_provider replaces hint_provider; _recent_conversation removed; stored_model/expected_model or stored_space/expected_space plus the mismatch-specific constant message on experience.unavailable; write_back threshold; config fields
└── experiments/engine.py            # background_provider replaces _hint_provider; write_back threshold
tests/
├── support.py                       # StubEmbeddingFunction → hashed bag of words, normalised, MODEL_NAME; SpyExperienceStore helper (records queries and writes)
├── fixtures/retrieval_recall.json   # NEW — the recall@k fixture (neutral placeholders)
├── unit/test_retrieval_query.py            # build_query: attacker role only, last two, label first, seed on turn 2 (011/FR-001)
├── unit/test_retrieval_selection.py        # select_patterns: floor, dedupe, order, k, off, boundaries, count identity (011/FR-003, FR-004, FR-005, SC-002, SC-003)
├── unit/test_experience_store_controls.py  # query_patterns, write_pattern add/merge/off/family scope/library seed, hit_count across re-seed (011/FR-006, FR-007, FR-008, SC-004)
├── unit/test_experience_store_model.py     # model name and l2 space stamped/compared, EmbeddingModelMismatch, SpaceMismatch, 004 store stamped, store_error_kind (011/FR-009, FR-010, FR-011, SC-006)
├── unit/test_settings_experience.py        # (extend; five 004 tests already live here) defaults, off, invalid, Settings.retrieval (011/FR-012)
├── unit/test_retrieval_recall.py           # the fixture check (011/FR-014, SC-005)
├── unit/test_support_embedding.py          # the lexical stub: 0 for identical, 2 for disjoint, normalised, stable hash (011/FR-014)
├── unit/test_events.py                     # (extend) the new fields pass the catalogue (011/FR-013)
├── unit/test_experiment_engine.py, test_experiment_warming.py   # (update doubles) query_patterns, PatternWrite (011/FR-015)
├── integration/test_retrieval_query_isolation.py   # known markers never reach a query — API run and experiment run (011/FR-002, SC-001)
├── integration/test_retrieval_lines.py             # memory.retrieval and memory.writeback fields, identity, no text (011/FR-013, SC-007)
├── integration/test_startup_model_mismatch.py      # experience.unavailable embedding_model_mismatch, store disabled, run records memory_written false (011/FR-010, SC-006)
├── integration/test_api_base.py                    # (extend) config reports the two settings (011/FR-012)
├── integration/test_runs_experience.py             # (extend) a cold run's attacker input is unchanged (011/FR-015, SC-009)
├── integration/test_delete_clears_memory.py        # (update on purpose) the single-turn success merges into its seed instead of adding a pattern (011/FR-006, FR-008, SC-009)
└── e2e/test_us011_retrieval.py                     # one e2e (011/FR-018, SC-010)
specs/010-structured-logging/contracts/log-records.md   # the three rows (spec-change: note on the PR)
docs/technical-design.md, README.md, CLAUDE.md          # store section, settings, learned note
docs/roadmap.md                                         # last task: Retrieval controls → Done as 011; 012/013/014 renumbered (FR-019)
specs/011-retrieval-controls/traceability.md            # implementation PR: id → tests table
```

**Structure Decision**: the existing single package `src/kestrel/` + `ui/`. One new module in the `experience/`
package (the query rule and the selection are retrieval concerns, beside the hint formatter); everything else is a
change at an existing boundary — the store, the write-back, the two run starters, the catalogue, the settings.
`attack/graph.py` stays free of storage concerns (it still receives a plain callable), and the UI is untouched.

## Phase status

- Phase 0 (research): done — `research.md`.
- Phase 1 (design): done — `data-model.md`, `contracts/`, `quickstart.md`; Constitution Check re-evaluated after
  design: PASS (no new dependency, no new secret path, no change to evidence, caps or gates).
- Phase 2 (tasks): `/speckit-tasks` → `tasks.md`.
