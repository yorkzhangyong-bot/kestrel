# Implementation Plan: A/B Harness

**Branch**: `007-impl` (implementation) — spec approved in **Spec-PR #4** (branch `007-ab-harness`, merged) | **Date**: 2026-10-30 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/007-ab-harness/spec.md`

## Summary

Answer "does X make attacks more effective?" with evidence. A **campaign** (one owned target, a set of attack families, a mode, N reps per family) is run under two **arms** that differ in at least one field (attacker model, judge model, retrieval on/off, turn cap, token budget); Kestrel runs arm A's full campaign then arm B's, and compares the outcomes.

Every run is an ordinary feature-002/003/004 run — stored, judged canary-first, and (by default) written back — produced by the existing `execute_run` / `execute_adaptive_run`. A **cold arm** disables write-back so arm B is not warmed by arm A; the experiment records the order the arms ran and which arm(s) wrote back. Per-arm results split success into **confirmed** (hard evidence) and **suspected** (judge opinion) per Principle II, with mean turns to success, mean tokens and estimated cost, and per-family / per-OWASP breakdowns. The comparison carries a **Wilson** interval per rate plus a **two-proportion z-test** on the overall confirmed rate, with a small-sample caveat — never a bare percentage at small N.

This feature **adds** the campaign/arm/experiment layer, the comparison and its statistics, a per-model price setting, experiment API endpoints, and an Experiments screen. It **reuses** features 002–005 (runs, attack library, judge, experience store, report renderer) and adds **no new attack content**. One end-to-end test: a 2-arm experiment against the HS-code target, N=1, retrieval off vs on, producing a comparison.

## Technical Context

**Language/Version**: Python 3.12 (Principle X).

**Primary Dependencies**: FastAPI, Streamlit, httpx, LangGraph (via the reused adaptive loop), ChromaDB (reused experience store), markdown-it-py (reused report renderer), pytest. **No new runtime dependency** — the Wilson score interval and the two-proportion z-test are implemented with the standard-library `math` only (Principle X; `math.erf` gives the normal CDF for the p-value).

**Storage**: the existing single SQLite file via stdlib `sqlite3`, no ORM. Schema **v5 → v6** (additive: three new tables, no changes to existing tables). ChromaDB experience store reused unchanged.

**Testing**: pytest — unit (stats, results/cost, engine with fakes, store v6, validation), integration (API create/status/result, UI boundary), and **one** e2e against the HS-code target (Principle VII). Tests-first. Every test file is scoped for the feature-007 traceability gate (`FEATURE = "007"` marker, or `007/FR-xxx` tokens where sample ids would otherwise leak), so citations count for 007 only.

**Target Platform**: local or hosted FastAPI service + Streamlit UI (the existing deployment).

**Project Type**: web service (FastAPI) + Streamlit front end — the existing single-project layout.

**Performance Goals**: not latency-bound. An experiment is many runs and is intentionally long-running; it is bounded by hard caps (max runs, total token budget, wall-clock) and executes in the background with status polling.

**Constraints**: an arm carries only model **names** and settings — no target header, key, or secret — in storage, API payloads, reports, and logs (Principle IV). One owned target per experiment, behind the existing permission/terms gate (Principle VIII). Every run writes back by default (Principle V); a cold arm's write-back is disabled only as an explicit, recorded experimental control (see Constitution Check).

**Scale/Scope**: single-user MVP. A default campaign is 4 families × 3 reps × 2 arms = 24 runs; caps keep any experiment finite.

## Constitution Check

*GATE: must pass before Phase 0 research; re-checked after Phase 1 design. Result: **PASS** (one justified deviation, tracked below).*

| Principle | How this feature complies |
| --- | --- |
| I — security, not quality | Reuses the existing security runs; measures attack effectiveness, not quality. |
| II — hard evidence over opinion | Per-arm success is reported **twice** — confirmed (canary/hard evidence) and suspected (judge) — never conflated; the significance comparison's primary verdict is the **confirmed** rate (clarified 2026-10-29). |
| III — every report states the attacker | The experiment report names **both** arms' attacker models and versions and their judge models. Each arm row records `attacker_model` / `judge_model`. |
| IV — secrets never leave the vault | Arms store only model names + numeric settings. Target credentials stay in the vault; the engine resolves headers per run exactly as `POST /api/runs` does, and never copies them into an arm, a payload, a report, or a log. A test asserts no arm/result/log carries a header value. |
| V — learn from every run | Runs write back by default. The cold-arm toggle disables write-back **only** for an explicitly configured arm, and the skip is **recorded** (run `memory_written` stays null and the experiment notes the warming). Justified deviation — see Complexity Tracking. |
| VI — OWASP-mapped, fix-ready | The report's per-category table maps every row to an OWASP LLM Top 10 class (reusing `report.owasp`). |
| VII — tests first, thin slices | Unit tests precede implementation; one e2e (2-arm, N=1, retrieval off vs on) against the HS-code target exercises UI→API→engine→store. |
| VIII — bounded harm, owned only | Hard caps (max runs, total token budget, wall-clock) with clean stop + partial results; single owned target behind the permission gate; **no new attack content** — only the existing library and loops. |
| IX — simple for a vibe coder | One Experiments screen: pick a target, edit two arms, start, watch progress, read a side-by-side table, download the report. No YAML, no CLI. |
| X — fixed stack | Python 3.12, FastAPI, Streamlit, ChromaDB, sqlite3, pytest. Statistics use stdlib `math` — **no new dependency**. |

## Project Structure

### Documentation (this feature)

```text
specs/007-ab-harness/
├── spec.md              # approved in Spec-PR #4
├── plan.md              # this file
├── research.md          # Phase 0 — decisions
├── data-model.md        # Phase 1 — entities + SQLite v6
├── quickstart.md        # Phase 1 — validation scenarios
├── contracts/
│   ├── experiments-api.md     # create / status / result / report endpoints
│   ├── experiment-engine.md   # A-then-B runner, caps, cold-arm toggle
│   └── statistics.md          # Wilson interval + two-proportion z-test + cost
└── tasks.md             # Phase 2 — created by /speckit-tasks (not here)
```

### Source Code (repository root)

```text
src/kestrel/
├── experiments/                 # NEW — the A/B layer
│   ├── __init__.py
│   ├── engine.py                # run_experiment(): A-then-B, caps, cold-arm write-back toggle
│   ├── stats.py                 # wilson_interval(), two_proportion() — stdlib math only
│   ├── results.py               # aggregate per-arm results + comparison from stored runs
│   └── pricing.py               # cost from tokens × configured per-model price ("unavailable" fallback)
├── report/
│   ├── experiment.py            # NEW — experiment report model + render_experiment_markdown()
│   ├── model.py  render.py  owasp.py    # REUSED (render_html, owasp.TESTED)
├── store.py                     # EXTENDED — v6 tables + experiment methods on TargetStore
├── settings.py                  # EXTENDED — model_prices + experiment cap defaults
├── runs.py                      # REUSED; execute_run gains a 1-line judge-token passthrough (foundational)
├── experience/writeback.py      # REUSED (write_back called conditionally by the engine)
├── attacks/library.py           # REUSED (families, pick)
├── judge/client.py attack/attacker.py   # REUSED (per-arm JudgeClient / AttackerClient)
└── api/
    ├── main.py                  # EXTENDED — /api/experiments endpoints + background task
    └── schemas.py               # EXTENDED — arm/campaign/caps in; status/result/comparison out

ui/
├── app.py                       # EXTENDED — render_experiments() section
└── api_client.py                # EXTENDED — create_experiment / experiment_status / result / report

tests/
├── unit/                        # stats, pricing, results, engine (fakes), store v6, schema validation
├── integration/                 # API create/status/result; UI boundary
└── e2e/                         # one: 2-arm N=1 retrieval off vs on vs the HS-code target
```

**Structure Decision**: keep the established single-project layout. The A/B logic lives in a new `src/kestrel/experiments/` package so the engine, statistics, cost and result aggregation are pure and unit-testable without HTTP. Persistence extends the existing `TargetStore` (schema v6) rather than introducing a second store class, matching how runs, canaries and recommendations already live there. The experiment report reuses `report.render.render_html` and `report.owasp`, adding only a comparison-shaped Markdown builder.

**One foundational change to reused code**: `execute_run` threads the judge's already-captured token count (`ParsedVerdict.tokens`) into the run record, so **single-turn** arms report tokens and cost too (no schema change, no new field; the judge client already parses `usage`). This removes any mode-specific tokens/cost gap — every arm reports mean tokens and estimated cost (priced at the arm's primary model: attacker for adaptive, judge for single-turn).

## Complexity Tracking

| Violation | Why needed | Simpler alternative rejected because |
| --- | --- | --- |
| Principle V (a cold arm skips experience-store write-back) | FR-005 requires a fair retrieval-on-vs-off comparison; if arm A (warm) wrote back, arm B (retrieval on) would retrieve arm A's fresh patterns and be "warmed", confounding the headline result. Disabling write-back for the cold arm is the control that keeps the test honest. | Leaving write-back always on would confound every retrieval experiment — the feature's main use case. The skip is **not** the "bug" Principle V forbids (an unintended, silent non-write-back): it is **opt-in per arm** and **recorded** (the run stays `memory_written = null` and the experiment stores the order + warming applied), so it remains auditable (FR-016). An isolated per-arm store was rejected as heavier than the spec's chosen mechanism (shared store + recorded toggle). |
