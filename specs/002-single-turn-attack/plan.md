# Implementation Plan: Run One Single-Turn Attack and Judge the Result

**Branch**: `002-single-turn-attack` (no branch created; work is on `master`) | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-single-turn-attack/spec.md`

## Summary

Pick a saved target, pick an attack family, send one prompt from a built-in library, and get a verdict. Judging is canary first: an exact match of a declared canary in the reply is hard evidence and settles the run without a model. Everything else goes to a judge model, whose verdict is recorded as opinion, never as confirmed.

The slice is UI → API → store, as in feature 001. Streamlit renders and calls the API; all logic stays in FastAPI. The attack send reuses feature 001's tester wholesale, so the hosting guard, redirect refusal, size cap and failure steps apply unchanged. The judge is one HTTPS call made with `httpx`, which the project already depends on, so this feature adds no new dependency.

## Technical Context

**Language/Version**: Python 3.12 (uv-managed 3.12.14), unchanged from feature 001.

**Primary Dependencies**: FastAPI, Streamlit, httpx, cryptography, uvicorn, pytest — all already present. **No new dependency.** The judge is an HTTPS call to an OpenAI-compatible chat completions endpoint, made with the `httpx.AsyncClient` already used to call targets (Principle X asks for a one-line justification per new dependency; there is none to justify).

**Storage**: the existing SQLite file (`data/kestrel.db`), no ORM. `meta.schema_version` moves 1 → 2, adding two tables and leaving feature 001's tables untouched.

**Testing**: pytest. Unit and integration offline; three end-to-end tests behind the `e2e` marker, which need `OPENROUTER_API_KEY`.

**Target Platform**: the user's own machine (`KESTREL_MODE=local`) or hosted; the hosting guard from feature 001 governs both.

**Project Type**: web application in one repo — FastAPI service, Streamlit screen, plus the sacrificial target as its own uv project.

**Performance Goals**: a run is capped at 90 seconds end to end — 60 for the send, 30 for the judge (FR-013, SC-001). A canary-settled run makes no model call and finishes in whatever the send took.

**Constraints**: Streamlit only renders and calls the API, importing nothing from the `kestrel` package. Target text is rendered as plain text only. Auth header values never reach the judge, the run record, or any log.

**Scale/Scope**: single user, one run at a time per target, a library of about 20 prompts, runs accumulating per target with no cap in this feature.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Verdict | How this feature satisfies it |
|---|---|---|
| I. Scope is security, not quality | PASS | This is the first security test. No quality metric is collected. |
| II. Hard evidence over opinion | PASS | Canary match settles a run without a model (FR-016). Every run records whether its verdict is hard evidence or opinion, and a judge-only verdict is never shown as confirmed (FR-018). |
| III. Every report states the attacker model | PASS | Every run records the judge model with its version and the attacker source, which here is the library and its version, not a model (FR-019). |
| IV. Secrets never leave the vault | PASS | Header values go only to the target as headers. They are masked out of the reply before it is stored, displayed or sent to the judge (FR-015, FR-020). |
| V. Learn from every run | **VIOLATION** | Runs do not write back to the attack-pattern store, because the store does not exist yet. Justified in Complexity Tracking below. |
| VI. OWASP-mapped, fix-ready findings | PASS | Every prompt carries an OWASP LLM Top 10 category and every run stores it (FR-002, FR-027), so a fix action can attach to a run later. |
| VII. Tests first, thin slices | PASS | One vertical slice, unit tests before implementation, three end-to-end tests against the sacrificial target (SC-008). |
| VIII. Only attack what you own | PASS | Permission gate (FR-009), plain conversational single message with no repetition (FR-004), hard cap on turns (one) and on the judge's tokens (FR-022), 90-second ceiling (FR-013). |
| IX. Simple enough for a vibe coder | PASS | Pick a target, pick a family, click Run. The judge model has a working default, so no configuration is needed to start. Without `OPENROUTER_API_KEY` the feature still runs and canary evidence still works; judged runs end "unclear" (FR-021) rather than failing. |
| X. Stack is fixed for the MVP | PASS | No new dependency. LangGraph is in the fixed stack but is not used here: one prompt and one judge call need no graph. It arrives with multi-turn attacks. |

**Post-design re-check (after Phase 1)**: unchanged. The design introduced no new dependency, no new secret store and no new rendering path. The single violation is still Principle V, with the same justification.

## Project Structure

### Documentation (this feature)

```text
specs/002-single-turn-attack/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── kestrel-api.md       # new and changed API routes
│   ├── attack-library.md    # the data file format and its rules
│   ├── judge.md             # what the judge is asked and what it must return
│   └── ui-screen.md         # the attack panel and the runs list
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
src/kestrel/
├── settings.py              # changed: judge model, judge key, judge limits
├── secrets.py               # unchanged
├── store.py                 # changed: schema v2, canaries, runs, migration
├── connection/              # unchanged; the tester is reused as-is
│   ├── tester.py
│   └── ...
├── attacks/                 # new
│   ├── library.py               # load, validate and index the prompt files
│   └── data/
│       ├── library.json             # version, and the prompts with provenance
│       └── SOURCES.md               # where each prompt came from
├── judge/                   # new
│   ├── client.py                # one HTTPS call, with timeout and token caps
│   └── verdict.py               # parse and validate what came back
├── runs.py                  # new: run one attack end to end (send → evidence → judge → store)
└── api/
    ├── main.py                  # changed: new routes, start-up sweep of interrupted runs
    ├── schemas.py               # changed: canary, run and library models
    └── terms.md                 # changed: version 2, judge disclosure

ui/
├── app.py                   # changed: canary rows, attack panel, runs list
└── api_client.py            # changed: the new API calls

targets/hs_code/
├── app.py                   # changed: canary in the system prompt, tool loop
├── tools/send_email.py      # new: fake tool that records instead of sending
└── ...

tests/
├── unit/                    # library, canary matching, verdict parsing, judge client, migration
├── integration/             # API routes and the UI boundary
└── e2e/                     # three end-to-end tests (SC-008)
```

**Structure Decision**: feature 001's layout is kept and extended. Two new packages, `attacks/` and `judge/`, hold the only genuinely new concerns; `runs.py` is the thin orchestration that joins the existing tester to them. `store.py` keeps owning all SQL, so there is still exactly one module that touches the database.

## Deviations from the mockup and the diagram

[docs/ui-mockup.html](../../docs/ui-mockup.html) and [docs/architecture.html](../../docs/architecture.html) show the finished MVP. This feature is a slice of it, so it deviates:

| Mockup or diagram shows | This feature | Why |
|---|---|---|
| "Run #14 · Running · 37 / 60 attacks" — a run is a batch | A run is **one** attack and its verdict | The spec defines it that way. The batch concept is out of scope. |
| "Max turns per attack", "[turn 3] attacker: …" | One turn only | Multi-turn is out of scope. |
| Attack success rate, judge/classifier agreement, results by family | None | Aggregate statistics need many runs; they arrive with the report feature. |
| "Same 60 attacks, v1 vs v2 (patched)" | None | The A/B harness is explicitly out of scope. |
| Live attack trace | The prompt, the reply and the verdict, after the run | A trace needs streaming and multi-turn. |
| Attack families as a multi-select | One family per run | One attack per run. |
| "after each run: write back what worked / failed" | Not done | Principle V deferral, below. |

**A naming conflict worth settling now.** The mockup's "Run #14" is a *batch* of 60 attacks; this feature's "run" is *one* attack. Both cannot stay. The plan keeps "run" as the spec defines it, and reserves **"scan"** for the later batch, so the mockup's "Run #14" becomes "Scan #14" when that feature lands. Choosing the other way would mean renaming this feature's table and API before it ships.

## Complexity Tracking

> Filled because the Constitution Check has one violation.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Principle V: runs do not write back to the ChromaDB attack-pattern store, and the principle calls such a run a bug | The store does not exist. Building it inside this feature would pull in ChromaDB, an embedding choice and a retrieval design, turning a thin slice into the largest feature in the project — against Principle VII. | Building the store now was rejected as too large for one slice. Dropping the principle was rejected as dodging a gate. Instead the run record already carries everything a write-back needs — attack family, OWASP category, verdict, evidence basis and target — so the store feature can backfill existing runs without a schema change. **This must be closed by the store feature, or Principle V amended with a version bump; it must not survive the MVP.** |
