# Implementation Plan: Learn From Every Run — Attack-Pattern Store and Per-Target Memory

**Branch**: `004-attack-pattern-memory` | **Date**: 2026-10-24 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-attack-pattern-memory/spec.md`

## Summary

Add a local ChromaDB store that lets Kestrel learn from every run, closing Principle V. One collection holds two kinds of record, typed by metadata: anonymised **patterns** (seeded idempotently from the attack library at start-up, and added to by each successful run) and per-target **memory** (one record written after every run, succeeded or not). Before each attacker turn of an adaptive run — when the per-run "use prior experience" switch is on (default) — Kestrel retrieves family-scoped patterns by semantic similarity plus this target's own memory by exact id, and offers them to the attacker as hints; it also feeds an optional, user-typed target purpose description regardless of the switch. A per-target profile view summarises a target's memory, deleting a target deletes its memory, and a write-back that fails is made loud (the attack result is kept, the run is flagged `memory_written = false`, a warning shows, an error is logged).

The slice reuses features 001–003 wholesale — targets, the single-turn and adaptive run paths, the judge and its per-turn progress notes, canary matching, masking, run storage, the start-up sweep and the sacrificial target. The new parts are the ChromaDB `ExperienceStore`, the summary builder, the retrieval-hint provider wired into the attacker, the write-back step, two new target/run fields (`description`, `memory_written`), and the profile view. Model calls are unchanged; embeddings run locally through Chroma's default function.

## Technical Context

**Language/Version**: Python 3.12 (uv-managed), unchanged.

**Primary Dependencies**: FastAPI, Streamlit, httpx, cryptography, uvicorn, LangGraph, pytest — all present — plus **ChromaDB** (new). Principle X fixes ChromaDB in the MVP stack and this feature *is* the store, so it needs no further justification; it is listed in Complexity Tracking for visibility. ChromaDB brings `onnxruntime` + `tokenizers` for its default local embedding function. No model SDK is added; attacker and judge calls stay plain `httpx`.

**Storage**: the existing SQLite file (`meta.schema_version` 3 → 4: add `targets.description` and `runs.memory_written`, both additive), **plus** a new local ChromaDB store at `data/chroma/` (one collection `kestrel_experience`, records typed `pattern`/`memory`, versioned in collection metadata).

**Testing**: pytest. Unit and integration offline — the `ExperienceStore` takes an injectable embedding function so tests use a deterministic stub (no model download, no network). One end-to-end test behind the `e2e` marker uses the real default embeddings and `OPENROUTER_API_KEY`; the first e2e run downloads ChromaDB's default local embedding model (~80 MB) once, then it is cached.

**Target Platform**: the user's own machine or hosted; the feature-001 hosting guard is unchanged.

**Project Type**: web application in one repo — FastAPI service, Streamlit screen, plus the sacrificial target as its own uv project (reused unchanged).

**Performance Goals**: retrieval adds one local `query` and one local `get` per warm adaptive turn (milliseconds, offline); write-back adds one or two local writes per run. Adaptive runs stay bounded by feature 003's three caps, unchanged.

**Constraints** (Principle IV, central here): no target URL, display name, or auth header value ever reaches a pattern or memory record, a hint shown to the attacker, the judge, a log line, or the profile view. Memory stores only a sanitised one-line summary and an internal target id; the summary is a fixed, bounded, single-line shape so target-influenced text cannot act as an instruction (no self-injection). Streamlit only renders and calls the API.

**Scale/Scope**: single user, one run at a time per target; memory grows by one record per run; patterns grow by the library seed plus one per success (no pruning this feature).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Verdict | How this feature satisfies it |
|---|---|---|
| I. Scope is security, not quality | PASS | Learning makes the security test stronger over time; no quality metric is introduced. |
| II. Hard evidence over opinion | PASS | Unchanged. Evidence rules are untouched: a canary still decides a run by hard evidence; patterns/memory are only hints to the attacker and never change a verdict. |
| III. Every report states the attacker model | PASS | Every memory record carries the attacker model (FR-007); the run already records it (feature 003). |
| IV. Secrets never leave the vault | PASS | No URL/name/header reaches any record, hint, log or the profile (FR-005, FR-011, FR-012, FR-023); records identify a target only by internal id; summaries are sanitised (FR-013). SC-004/SC-008 assert this. |
| V. Learn from every run | **PASS (closes the deferral)** | Every run writes exactly one memory record; successes also write a pattern; a failed write-back is loud (FR-006, FR-009, FR-010). This feature removes the Principle V deferral carried by features 002–003. |
| VI. OWASP-mapped, fix-ready findings | PASS | Every pattern and memory record carries family and OWASP category (FR-005, FR-007). |
| VII. Tests first, thin slices | PASS | One vertical slice (UI → API → store), unit tests before implementation, one end-to-end test against the sacrificial target (FR-026, SC-012). |
| VIII. Only attack what you own | PASS | Permission/terms gates and the three caps are unchanged; retrieved items are hints, not commands, and cannot override the plain-conversation rule or the caps (FR-019). |
| IX. Simple enough for a vibe coder | PASS | Warm is the default and needs no setup; the switch, the one-line purpose field and the profile are the only new controls. |
| X. Stack is fixed for the MVP | PASS | ChromaDB is named in the fixed stack; embeddings use its built-in local function. No other new dependency. |

**Post-design re-check (after Phase 1)**: unchanged, and **Principle V flips from the feature-003 VIOLATION to PASS**. The design adds one local store, two additive SQLite columns, a retrieval-hint path (masked, sanitised, hints-only) and a write-back path (fail-loud). No new secret path is created: records and hints carry only summaries, internal ids and non-secret metadata; the attacker still receives only masked conversation plus sanitised, clearly-labelled background. No new rendering path that renders untrusted text as markup.

## Project Structure

### Documentation (this feature)

```text
specs/004-attack-pattern-memory/
├── plan.md              # This file
├── research.md          # Phase 0 output (R1–R13)
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── experience-store.md   # the ChromaDB store: collection, records, seed/write/retrieve/delete
│   ├── writeback.md          # the after-every-run write-back and fail-loud behaviour
│   ├── kestrel-api.md        # description field, use_prior_experience, memory_written, profile endpoint
│   ├── attacker.md           # feature 003's attacker, extended with sanitised hints
│   └── ui-screen.md          # the experience toggle, purpose field, profile view, write-back warning
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
src/kestrel/
├── settings.py              # changed: chroma path, pattern k, memory cap (all from env, positive_int)
├── experience/              # new package: everything ChromaDB
│   ├── __init__.py
│   ├── store.py             # ExperienceStore: Chroma client, seed/write_memory/write_pattern/retrieve/delete/version
│   ├── summary.py           # build + sanitise the one-line situation summary (no model calls)
│   └── hints.py             # format retrieved patterns + memory + purpose into the attacker hint block
├── attacks/
│   └── library.py           # unchanged surface; its prompts are the seed source
├── attack/
│   ├── attacker.py          # changed: next_message accepts an optional sanitised `hints` block
│   └── graph.py             # changed: attacker_node calls a hint_provider each turn (no Chroma import)
├── runs.py                  # unchanged core; write-back is wired in the API layer
├── store.py                 # changed: schema v4 — targets.description, runs.memory_written; set_memory_written; delete still cascades SQLite
└── api/
    ├── main.py              # changed: build ExperienceStore; seed on start-up; wire hint_provider + write-back; profile endpoint; delete also clears memory
    └── schemas.py           # changed: description in target in/out; RunRequest.use_prior_experience; RunDetail.memory_written + use_prior_experience; ProfileOut

ui/
├── app.py                   # changed: experience toggle, purpose field, profile section, write-back warning
└── api_client.py            # changed: pass use_prior_experience + description; get_profile

targets/hs_code/             # reused unchanged

tests/
├── unit/                    # ExperienceStore (stub embedder), summary + sanitisation, hints formatting, schema v4 migration
├── integration/             # seeding idempotency, write-back after each run + fail-loud, warm/cold retrieval, delete clears memory, profile endpoint, UI toggle/field/profile
└── e2e/                     # two warm runs; the second run's attacker receives ≥1 memory record from the first
```

**Structure Decision**: feature 003's layout is kept. All ChromaDB lives in a new `experience/` package so the store, the summary builder and the hint formatter are isolated and unit-testable; `attack/graph.py` stays free of storage concerns by calling a `hint_provider` closure the API supplies. `store.py` still owns all SQL (two additive columns). Write-back is orchestrated in `api/main.py` — the one place runs are created — so "after every run" is guaranteed without touching the feature-002/003 run paths.

## Deviations from the mockup and the diagram

[docs/ui-mockup.html](../../docs/ui-mockup.html) and [docs/architecture.html](../../docs/architecture.html) show the eventual MVP, which includes "after each run: write back what worked / failed" and a ChromaDB store feeding the attacker. This feature builds exactly that store, so it converges toward the diagram. Where it is still thinner:

| Mockup or diagram shows | This feature | Why |
|---|---|---|
| ChromaDB store of patterns + per-target memory, feeding the attacker | Exactly this | The core of the feature. |
| "after each run: write back what worked / failed" | Exactly this (memory always; pattern on success) | Closes Principle V. |
| Cross-target trait matching / memory consolidation | Not done | Explicit out-of-scope; recent-first cap and every-success writes are deliberately simple this slice. |
| Risk score, report, A/B of attackers | Not done | Features 005/006; this feature records the per-run `use_prior_experience` flag so 006 can compare warm vs cold. |

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|-----------|------------|-------------------------------------|
| New dependency: ChromaDB (+ onnxruntime, tokenizers) | Principle X names ChromaDB as the MVP store, and this feature is the store. Default local embeddings avoid any embedding API. | A hand-rolled store (SQLite + keyword match) was considered and rejected: it would not give semantic pattern retrieval, would diverge from the fixed stack and the diagram, and would be thrown away at feature 006. The offline-test promise is kept by injecting a stub embedding function. |
| Two additive SQLite columns (`targets.description`, `runs.memory_written`) | The purpose description (FR-020) and the fail-loud flag (FR-010) belong on the relational row, not the vector store. | Storing them only in Chroma was rejected: the description is a target field edited in the form, and `memory_written` must be returned on the run detail the API already builds from SQLite. |
