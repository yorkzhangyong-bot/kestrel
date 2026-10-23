# Implementation Plan: Run a Multi-Turn Adaptive Attack and Judge the Result

**Branch**: `003-adaptive-attack` (no branch created; work is on `master`) | **Date**: 2026-10-24 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-adaptive-attack/spec.md`

## Summary

Add an adaptive attack mode: an attacker model holds a conversation with the target, opening from a library prompt and adapting each turn from the reply and the judge's feedback, until it succeeds or hits a cap. The loop is a LangGraph graph of attacker and judge steps (Principle X). After each turn the canary is checked first and the judge is consulted only if nothing matched (Principle II), exactly as feature 002. The full conversation is stored, masked, and shown turn by turn.

The slice reuses feature 002 wholesale — the permission and terms gates, the connection tester, canary matching, the judge client, reply masking and cutting, run storage, the start-up sweep and the sacrificial HS-code target. The genuinely new parts are the attacker model client, the LangGraph loop, the per-run budgets, and the conversation storage and display. The judge gains one field — a short "how close" note — so each judge call also steers the next attacker turn.

## Technical Context

**Language/Version**: Python 3.12 (uv-managed), unchanged.

**Primary Dependencies**: FastAPI, Streamlit, httpx, cryptography, uvicorn, pytest — all present — plus **LangGraph** (new). Principle X fixes LangGraph in the MVP stack and the feature requires the loop to be a graph, so it needs no further justification; it is listed in Complexity Tracking for visibility. LangGraph is used only to orchestrate the loop; the attacker and judge model calls stay plain `httpx` calls to an OpenAI-compatible endpoint, as feature 002's judge does, so Kestrel adds no model SDK.

**Storage**: the existing SQLite file, no ORM. `meta.schema_version` moves 2 → 3, adding columns to `runs` and a `run_turns` child table; feature 001/002 tables are otherwise untouched.

**Testing**: pytest. Unit and integration offline with stub attacker/judge/sender; one end-to-end test behind the `e2e` marker, which needs `OPENROUTER_API_KEY`.

**Target Platform**: the user's own machine or hosted; the hosting guard from feature 001 governs both.

**Project Type**: web application in one repo — FastAPI service, Streamlit screen, plus the sacrificial target as its own uv project (reused unchanged).

**Performance Goals**: a run is bounded by three caps, whichever is reached first — 6 turns, a per-run token budget across all attacker and judge calls, and a wall-clock limit (defaults in [research.md](./research.md) R3). Typical runs against a responsive target finish in well under the time limit.

**Constraints**: Streamlit only renders and calls the API. Attacker messages, target replies and the judge's note are shown as plain text only. Auth header values never reach the attacker, the judge, the stored conversation, or any log.

**Scale/Scope**: single user, one run at a time per target, conversations of up to the turn cap, runs accumulating per target.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Verdict | How this feature satisfies it |
|---|---|---|
| I. Scope is security, not quality | PASS | A stronger, multi-turn security test. No quality metric. |
| II. Hard evidence over opinion | PASS | Each turn: canary first; the judge only if nothing matched. A canary stops the run as "succeeded" by hard evidence; a judge verdict is opinion and never shown as confirmed (FR-007, FR-018). |
| III. Every report states the attacker model | PASS | Every run records the attacker model and version, the judge model, and the budget allowed and used (FR-015). This is the first feature whose attacker is a model, so Principle III bites directly. |
| IV. Secrets never leave the vault | PASS | The attacker and judge receive only the conversation and what they need; header values are masked out of every turn before it is stored, judged or sent on (FR-017, FR-021). |
| V. Learn from every run | **VIOLATION** | Adaptive runs do not write back to the attack-pattern store, because the store does not exist yet. Deferred to feature 004, as in feature 002; see Complexity Tracking. |
| VI. OWASP-mapped, fix-ready findings | PASS | The seed prompt's OWASP category is recorded on the run, as in feature 002 (FR-020). |
| VII. Tests first, thin slices | PASS | One vertical slice (UI → API → graph → store), unit tests before implementation, one end-to-end test against the sacrificial target (SC-009). |
| VIII. Only attack what you own | PASS | Permission and terms gates before anything is sent (FR-003); plain conversation only, no flooding (FR-009); hard caps on turns, tokens and time (FR-010, FR-011). |
| IX. Simple enough for a vibe coder | PASS | A Single-turn / Adaptive toggle and one Run button; the attacker and caps have working defaults, so nothing needs configuring to start. |
| X. Stack is fixed for the MVP | PASS | LangGraph (in the fixed stack) drives the loop; no other new dependency. Model calls stay on `httpx`. |

**Post-design re-check (after Phase 1)**: unchanged. The design adds LangGraph (fixed stack), one env-configured attacker client mirroring the judge, a `run_turns` table and a mode toggle. No new secret path, no new rendering path. The single violation is Principle V, with the same justification as feature 002.

## Project Structure

### Documentation (this feature)

```text
specs/003-adaptive-attack/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── kestrel-api.md       # the mode field, the conversation in a run, config additions
│   ├── attacker.md          # the attacker model: config, what it sees, what it returns
│   ├── judge.md             # feature 002's judge, extended with the "how close" note
│   ├── adaptive-loop.md     # the LangGraph graph: states, nodes, transitions, caps
│   └── ui-screen.md         # the mode toggle and the conversation display
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
src/kestrel/
├── settings.py              # changed: attacker model/key/base-url, and the three caps, all from env
├── judge/
│   ├── client.py            # changed: optional "progress" note in the judged answer
│   └── verdict.py           # changed: ParsedVerdict gains an optional progress field
├── attack/                  # new
│   ├── attacker.py          # the attacker model client (one httpx call, like the judge)
│   └── graph.py             # the LangGraph attacker/judge loop and its state
├── runs.py                  # changed: single-turn stays; adaptive delegates to attack.graph
├── store.py                 # changed: schema v3 — runs columns + run_turns table
└── api/
    ├── main.py              # changed: mode on POST /api/runs, conversation in run detail, config
    └── schemas.py           # changed: RunRequest.mode, RunDetail.turns, ConfigOut.attacker + caps

ui/
├── app.py                   # changed: Single-turn/Adaptive toggle, conversation display
└── api_client.py            # unchanged surface (run_attack already posts the run request)

targets/hs_code/             # reused unchanged

tests/
├── unit/                    # attacker client, verdict progress, the graph loop, schema v3 migration
├── integration/             # POST /api/runs mode=adaptive, run detail with turns, UI toggle + display
└── e2e/                     # one adaptive run against the sacrificial target
```

**Structure Decision**: feature 002's layout is kept. A new `attack/` package holds the only new concerns — the attacker client and the graph; `runs.py` keeps orchestrating and simply routes an adaptive request into `attack.graph`. `store.py` still owns all SQL. The judge is extended in place rather than forked, so single-turn and adaptive share one judge.

## Deviations from the mockup and the diagram

[docs/ui-mockup.html](../../docs/ui-mockup.html) and [docs/architecture.html](../../docs/architecture.html) show the eventual MVP — a LangGraph attacker/target/judge loop and a live attack trace. This feature builds that loop for the first time, so it converges toward the diagram rather than deviating. Where it is still thinner:

| Mockup or diagram shows | This feature | Why |
|---|---|---|
| "LangGraph attack loop · adaptive, up to N turns per attack" | Exactly this, with N = 6 by default | The core of the feature. |
| A live, streaming attack trace | The conversation shown turn by turn **after** the run | Streaming a running graph to the screen is extra; the turns are all shown once the run finishes. |
| "after each run: write back what worked / failed" | Not done | Principle V deferral (feature 004). |
| Attack success rate, A/B of two attackers | Not done | Aggregates and the A/B harness are later features (005, 006); this feature makes the caps and models env-configurable so 006 can vary them without code changes. |

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| New dependency: LangGraph | The feature requires the attacker/judge loop to be a graph (Principle X names LangGraph in the fixed MVP stack). It also sets the pattern the later multi-node features build on. | A hand-rolled `while` loop was considered and rejected: it would meet this feature alone but diverge from the fixed stack and from the diagram, and would be rewritten at the first branching graph. Model calls still stay on `httpx`, so only orchestration is added. |
| Principle V: adaptive runs do not write back to the ChromaDB attack-pattern store | The store does not exist; building it here would pull in ChromaDB, embeddings and retrieval, dwarfing a thin slice (Principle VII). | Same as feature 002. The run and its `run_turns` already hold the family, OWASP category, verdict and full conversation a write-back needs. **Closes in feature 004 when the store lands, or Principle V is amended with a version bump; it must not survive the MVP.** |
