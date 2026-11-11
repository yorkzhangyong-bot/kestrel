# Implementation Plan: Versioned Prompts (009)

**Branch**: `009-versioned-prompts` | **Date**: 2026-11-11 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/009-versioned-prompts/spec.md`

## Summary

Give every model-facing prompt a tracked id + semantic version + content fingerprint in a code-resident **registry**
(`src/kestrel/prompt_registry.py`) backed by a committed fingerprint lock. Record which prompt version produced each
adaptive run turn and each judge verdict via an additive schema **v7** migration. A unit guard fails the suite when a
prompt's authored text changes without a version bump. Expose active versions on `GET /api/config` (UI + curl — no
new CLI). Add a prompt-version A/B **arm** to the 007 harness for the attacker/judge prompts. Report judge-eval
accuracy per judge prompt version. No behaviour change by default — current prompts seed at `1.0.0`.

Approach and rationale are in [research.md](research.md); shapes in [data-model.md](data-model.md) and
[contracts/](contracts/); validation in [quickstart.md](quickstart.md).

**Deviation from the spec (flagged):** FR-001 lists a *memory-summariser* prompt, but `experience/summary.py`
composes the writeback summary deterministically with **no model call** — there is no summariser prompt to version.
The registry therefore covers **three** model-facing prompt kinds: `attacker:<family>`, `judge`, `recommender`. No
behaviour is lost; recommend a one-line spec footnote in the implementation PR.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: FastAPI, Streamlit, LangGraph, httpx, ChromaDB, markdown-it-py (all existing). **No new
runtime dependency** — fingerprints use stdlib `hashlib.sha256`, version strings are validated with stdlib `re`,
and schema versioning reuses the existing `sqlite3` migration routine (Principle X satisfied).

**Storage**: SQLite (`src/kestrel/store.py`), `SCHEMA_VERSION "6" → "7"`, additive nullable columns only.

**Testing**: pytest — unit + integration offline (no keys), one `e2e` against the HS-code target, `judge_eval`
golden set (needs `OPENROUTER_API_KEY`). Tests-first (Principle VII).

**Target Platform**: local/hosted FastAPI service + Streamlit UI (Windows 11 dev; PowerShell).

**Project Type**: web service (FastAPI API) + Streamlit UI that only calls the API.

**Performance Goals**: no latency-sensitive path; registry is built once in-process; fingerprinting is O(prompt
size) at import/test time.

**Constraints**: no attack-library fixture text or target secret in the registry, lock, API, UI, or any commit
(FR-011/FR-012/SC-007); observability-only by default (FR-013/SC-003).

**Scale/Scope**: a handful of prompt ids (attacker families + judge + recommender); provenance on existing run/turn
volumes.

## Constitution Check

*GATE: must pass before Phase 0 and after Phase 1. Result: **PASS** — no violations.*

| Principle | Assessment |
|-----------|------------|
| I — security not quality | Provenance of security tooling; no quality metrics introduced. ✓ |
| II — hard evidence over opinion | Canary path untouched; feature records/compares provenance only. ✓ |
| III — report states attacker model | Strengthens it: adds prompt-version provenance alongside model/version. ✓ |
| IV — secrets never leave the vault | Registry/lock/API/UI carry only ids, versions, fingerprints, and the prompts' own authored text — no target auth/URL/name, no fixture text (FR-012/SC-007). ✓ |
| V — learn from every run | Writeback unchanged; summariser stays deterministic (the deviation above). ✓ |
| VI — OWASP-mapped, fix-ready | Unchanged. ✓ |
| VII — tests first, thin slices, one e2e | TDD; guard + provenance + config + arm + eval tests before code; one e2e on HS-code. ✓ |
| VIII — only attack owned, hard caps | Unchanged. ✓ |
| IX — simple for a vibe coder | Clarification avoided a new CLI (API + curl); no new user-facing flow. ✓ |
| X — stack fixed; new dep needs justification | **No new dependency.** ✓ |

Complexity Tracking: none required.

## Project Structure

### Documentation (this feature)
```text
specs/009-versioned-prompts/
├── plan.md            # this file
├── research.md        # Phase 0 — decisions D1–D11
├── data-model.md      # Phase 1 — registry ids, PromptEntry, lock, schema v7 columns
├── contracts/         # Phase 1 — api-config.md, api-experiments.md, prompt-registry.md
├── quickstart.md      # Phase 1 — US1–US5 validation
├── spec.md            # merged (PR #18)
└── tasks.md           # Phase 2 — /speckit-tasks (not created here)
```

### Source code (files this feature touches)
```text
src/kestrel/
├── prompt_registry.py        # NEW — PromptEntry, registry(), fingerprint(), has(), text_for(), verify_lock()
├── prompt_versions.lock.json # NEW — committed {id: {version: fingerprint}} (append-only)
├── store.py                  # schema v7: run_turns/runs/experiment_arms columns; _migrate accepts "6"; add_turn/finish_run/create_experiment record provenance; ExperimentArm fields
├── attack/attacker.py        # resolve active/arm-pinned attacker version+text from registry; expose provenance
├── judge/client.py           # resolve judge + recommender version+text; expose judge-prompt provenance
├── experiments/engine.py     # pin an arm's prompt version for its runs
├── api/
│   ├── schemas.py            # ConfigOut.prompts + PromptVersionOut; ARM_DIFF_FIELDS + validate_experiment + experiment_diff for prompt arms
│   └── main.py               # get_config() returns active prompt versions
ui/app.py                     # display active prompt versions (read from /api/config)
tests/
├── unit/test_prompt_registry.py        # guard (verify_lock), fingerprint, version validation (US2/FR-005/FR-006)
├── integration/test_provenance_*.py    # run_turns/runs provenance; config prompts; arm validation/refusal
├── eval/test_judge_accuracy.py         # group results by judge prompt version (US5/FR-010)
└── e2e/…                                # one e2e: provenance recorded on a real HS-code run
```

**Structure Decision**: single Python package `src/kestrel/` + `ui/` (existing layout); the registry is a new small
module beside `prompting.py`, not a package, and the lock is a committed data file. No architectural change.

## Phase status
- Phase 0 (research): **complete** — [research.md](research.md), all unknowns resolved, no `NEEDS CLARIFICATION`.
- Phase 1 (design): **complete** — [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md); Constitution re-checked → PASS.
- Phase 2 (tasks): run `/speckit-tasks` next.
