# Implementation Plan: Regression Replay (012)

**Branch**: `012-regression-replay` | **Date**: 2026-11-19 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/012-regression-replay/spec.md`

## Summary

Give Kestrel a way to re-check a finding instead of only finding new ones. A replay resends a past, succeeded
run's recorded attacker message(s) — verbatim, in order, with **no attacker model call** — to the same target under
its current connection settings and canaries, scores each reply exactly as a live run does (canary first, judge
second), and stops at the first success, exactly like a live adaptive run. The whole send/score/record loop is
**reused, not reimplemented**: a single-turn source is replayed through a thin new function shaped like
`runs.py::execute_run` (same one-shot judge call, no conversation); an adaptive source is replayed through one new
LangGraph function in `attack/graph.py` shaped like `run_adaptive`, with the existing `attacker_node` swapped for a
deterministic "take the next recorded message" step and `max_turns` capped at `min(source turn count, the
currently configured adaptive turn cap)` — which makes "ran out of recorded messages" and "hit the turn cap" the
same `decide_node` path the graph already has, so no new stopping condition is needed. The outcome against the
source — **fixed** / **still vulnerable** / **inconclusive** — is computed from the **sequence of each turn's own
result**, captured live as the replay runs (never from the run's one final `verdict` field, which a later turn
can silently overwrite ahead of an earlier, unresolved one — research D5), additionally requiring, for a
multi-message source, that the source's own winning turn was itself sent and judged failed; a small pure function
maps that to the outcome. A replay never calls `background_provider` or
`write_back` (no retrieval, no write-back), so the
shared pattern pool, per-target memory and the OWASP report are untouched by it. Storage needs one more rebuild of
`runs` (**schema v10**, following v9's documented procedure) to widen the `mode` CHECK and add a self-referencing
`source_run_id` and a `replay_outcome` column; everything else a replay records reuses existing columns and existing
provenance machinery (009/010) unchanged. A batch endpoint loops the same single-replay function oldest first,
under a new, configurable cap (`KESTREL_REPLAY_BATCH_MAX_RUNS`, default 20, confirmed with the product owner); a
new CI script (`scripts/check_replay.py`) calls that batch endpoint the way the UI calls the API and turns the
outcome mix into one of four exit codes (0/1/2/3, also confirmed with the owner). The UI gets one **Replay** button,
driven entirely by fields the API already computes (no eligibility logic in the screen, per FR-042).

Approach and rationale: [research.md](research.md) (D1–D17); shapes: [data-model.md](data-model.md) and
[contracts/](contracts/); validation: [quickstart.md](quickstart.md).

## Technical Context

**Language/Version**: Python 3.12 (uv-managed), unchanged.

**Primary Dependencies**: FastAPI, Streamlit, LangGraph, httpx, ChromaDB 1.5.9, markdown-it-py — all existing, all
unchanged. A replay reuses `langgraph.graph.StateGraph` the same way `attack/graph.py` already does; the CI script
uses only `httpx` and the standard library (`argparse`, `sys`), both already dependencies. **No new dependency,
required or optional** (Principle X, FR-048).

**Storage**: SQLite schema **v10**. `runs.mode`'s CHECK widens to include `'replay'`; `runs` gains
`source_run_id INTEGER REFERENCES runs(id) ON DELETE CASCADE` (self-reference, null for a non-replay run) and
`replay_outcome TEXT CHECK (replay_outcome IS NULL OR replay_outcome IN ('fixed', 'still_vulnerable',
'inconclusive'))`. Because SQLite cannot `ALTER` a CHECK constraint, this is a second full rebuild of `runs`
following the **same documented procedure and gotchas v9 already proved out** (foreign keys off before any DML,
the two new indexes issued as separate `execute()` calls rather than one script, `PRAGMA foreign_key_check` empty
before commit) — see [data-model.md](data-model.md) and research D3/D4. No other table changes: an adaptive
replay's sent messages go into `run_turns` exactly as a normal adaptive run's do (one row per sent turn); a
single-turn replay writes no `run_turns` row, exactly as a normal single-turn run does not. No ChromaDB change: a
replay never calls the experience store (FR-025/FR-026).

**Testing**: pytest; unit + integration offline with stub transports/judges and a `tmp_path` database (never
`data/kestrel.db`), plus one `e2e` test against the HS-code target. Tests first (Principle VII); every test carries
`012/FR-###` / `012/SC-###` or a module-level `FEATURE = "012"`. A new `tests/unit/test_store_migration_v10.py`
follows the `test_store_migration_v9.py` convention (CLAUDE.md "Learned notes", 2026-11-17).

**Target Platform**: local/hosted FastAPI service + Streamlit UI (Windows 11 dev; PowerShell); the CI script runs
anywhere `uv run python` and the Kestrel API are both reachable (a CI runner, not the dev machine).

**Project Type**: web service (FastAPI API) + Streamlit UI that only calls the API, unchanged; one new standalone
CLI script under `scripts/`.

**Performance Goals**: a replay costs at most as much as the live run it re-tests (same send/judge calls, same
caps, zero attacker calls — strictly fewer model calls than the source made); a batch of up to the configured cap
(20) runs those one at a time, so its worst case is bounded by `cap × (a single replay's own time limit)`. The UI
has no batch action (the spec asks only for a single-run **Replay** button); its one
HTTP call (`replay_run`) needs a timeout that covers one replay — the adaptive time limit plus a margin, the same
shape `run_attack`'s existing timeout already uses, never the batch's own, much larger bound. The CI script is the
one caller of the batch endpoint and sizes its own timeout for the batch's worst case (research D13).
No new background task and no polling: both new endpoints stay synchronous, exactly like `POST /api/runs` today
(FR-038).

**Constraints**: a replay must send the source's recorded text byte-for-byte, never re-masking or reconstructing it
(FR-001, Principle IV); no attacker model constructed or called (FR-002); no call to the experience store under any
outcome (FR-025/FR-026, Principle V's "a run that does not write back is a bug" explicitly does **not** apply to a
replay — see Constitution Check); no new report section and no duplicate finding (FR-027); the three existing hard
caps, the permission gate and the terms gate still apply before any replay row is claimed (FR-006); no attack text
on any log line, in the CI script's output, or in a test fixture (FR-045/FR-046, Principle IV).

**Scale/Scope**: single user, as the whole project is; a batch replays at most `KESTREL_REPLAY_BATCH_MAX_RUNS` (20)
runs of one target at a time; an adaptive replay sends at most `min(source.turns_used, the current adaptive turn
cap)` messages.

## Constitution Check

*GATE: must pass before Phase 0 and after Phase 1. Result: **PASS** — one principle (V) carries a justified,
recorded deviation; see Complexity Tracking below. No other violations.*

| Principle | Assessment |
|-----------|------------|
| I — security not quality | Replay re-tests a security finding against the current target; no quality metric is introduced. ✓ |
| II — hard evidence over opinion | Untouched: a replay's canary check still decides before the judge is asked, and `hard_evidence` is still set by a canary match alone (FR-007). The new `fixed`/`still vulnerable`/`inconclusive` outcome is a *comparison* label derived from the existing verdict, never a new evidence category. ✓ |
| III — report states attacker model | A replay names no attacker model because it used none (FR-022); the side-by-side still names the judge model and judge-prompt version behind each run's verdict (FR-017), so the report-adjacent comparison still states what decided it. ✓ |
| IV — secrets never leave the vault | A masked recorded message is resent exactly as stored, never unmasked (FR-001); the judge still never receives an auth value, the target URL or the target's name (FR-047), unchanged from 001. ✓ |
| V — learn from every run | **Justified deviation — see Complexity Tracking** (FR-025/FR-026, User Story 2), following the 007 precedent for an explicit, recorded skip of write-back. `memory_written` is recorded as "not attempted" (never a failure) so the skip is visibly deliberate, not a silent bug the Principle-V self-check would otherwise flag. ✓ |
| VI — OWASP-mapped, fix-ready | A replay copies its family and OWASP category from its source (FR-021) for its own display, but is excluded from the report's findings and recommendation calls (FR-027) — it re-checks a finding that is already mapped and fix-ready; it does not need its own mapping or its own recommendation. ✓ |
| VII — tests first, thin slices, one e2e | TDD per story; vertical slice store (schema v10) → replay engine (`replay.py`, `attack/graph.py`) → API → UI; one e2e (`tests/e2e/test_us012_replay.py`). ✓ |
| VIII — only attack owned, hard caps | The same permission box, terms gate and single-active-run-per-target constraint are checked before a replay row is claimed (FR-006); a replay's turn count is still bounded by the current adaptive turn cap (FR-011) and a batch is bounded by its own configurable cap (FR-031) — a *new* hard cap this feature adds, not a bypass of the existing ones. ✓ |
| IX — simple for a vibe coder | One button; the UI needs no new judgement calls because the API hands it a ready-made `replayable` flag, blocked reason and advisory (FR-040, FR-042) and a ready-made comparison (FR-017) — no new form, no new settings screen (the batch cap and the CI exit codes are environment/CLI, not UI). ✓ |
| X — stack fixed; new dep needs justification | **No new dependency**: the replay engine reuses LangGraph (already a dependency) and plain functions; the CI script uses `httpx` and the standard library, both already present. ✓ |

## Complexity Tracking

| Violation | Why needed | Simpler alternative rejected because |
| --- | --- | --- |
| Principle V (a replay never writes back to the experience store — no memory record, no pattern, under any outcome) | A regression replay exists to hold everything constant except time, so a difference in outcome is attributable only to what changed on the target's side (User Story 2); writing a replay back would double-count a success the shared pattern pool already holds from the source run, and would let a re-check of old material bias future attacks on **other** targets that draw on the same shared pattern pool. The owner's own requirement states this directly ("a replay never writes shared patterns or target memory"). | Writing back as a normal run would confound the shared pattern pool exactly the way an always-warm cold-arm would confound a 007 experiment (the direct precedent, `specs/007-ab-harness/plan.md:107-111`): the signal every other feature (004, 005, 011) relies on would include a fact Kestrel already knew, counted twice. The skip is **not** the silent, unintended non-write-back Principle V forbids: it is total (every replay, every outcome, no per-run toggle needed) and **recorded** (`memory_written` is "not attempted", never a failure; FR-024), so it stays auditable the same way the 007 cold arm's skip does. |

## Project Structure

### Documentation (this feature)

```text
specs/012-regression-replay/
├── plan.md              # this file
├── research.md          # Phase 0 — decisions D1–D17
├── data-model.md        # Phase 1 — schema v10, Run/Turn/Comparison/BatchEntry shapes, the outcome rule
├── contracts/            # Phase 1 — api.md, log-records-delta.md, ci-script.md (no separate store.md: the
│                         #   store-level shapes — schema v10, Run/TargetStore additions — live in data-model.md)
├── quickstart.md        # Phase 1 — per-story validation, the manual migration check, the e2e
├── checklists/requirements.md
├── spec.md
└── tasks.md             # Phase 2 — /speckit-tasks
```

### Source code (files this feature touches)

```text
src/kestrel/
├── replay.py                     # NEW — NotReplayable, ReplayOfReplay, check_replayable, compute_outcome,
│                                  #   execute_replay (dispatches single_turn/adaptive), BatchEntry, BatchResult,
│                                  #   execute_batch_replay, Comparison, TurnComparison, build_comparison
├── attack/graph.py                # judge_node/send_node/evidence_node/decide_node lifted to module-level,
│                                  #   parameterised functions shared by run_adaptive and the NEW
│                                  #   run_replay_adaptive(...) (research D14 — they are closures today, not
│                                  #   separately reusable); run_replay_adaptive defines its own
│                                  #   attacker_node/record_node beside run_adaptive's (a model call vs. a list
│                                  #   lookup; attacker_generated is always False for a replay, the turn's
│                                  #   attacker-prompt provenance only copied from source_turns[turn - 1] — the
│                                  #   judge-prompt provenance is never copied, it is
│                                  #   the replay's own current judge call (FR-022); a NEW
│                                  #   try/except around its own ainvoke() sets replay_outcome="inconclusive" on
│                                  #   a crash (research D15) — run_adaptive itself is untouched in behaviour
├── runs.py                       # UNCHANGED; replay.py imports match_canary/judge_ref
│                                  #   from here, as run_adaptive already does
├── store.py                      # SCHEMA_VERSION "10"; RUNS_COLUMNS_SQL (mode CHECK + source_run_id +
│                                  #   replay_outcome); _rebuild_runs_for_replay (new, beside
│                                  #   _rebuild_runs_with_autoincrement); Run.source_run_id/.replay_outcome;
│                                  #   claim_run(source_run_id=), finish_run(replay_outcome=);
│                                  #   list_replayable_runs(target_id)
├── events.py                      # CATALOGUE: run.start + source_run_id, run.end + replay_outcome, new
│                                  #   replay.batch.start / replay.batch.end; replay_batch_started/_ended helpers
├── settings.py                    # KESTREL_REPLAY_BATCH_MAX_RUNS (positive_int, default 20) ->
│                                  #   Settings.replay_batch_max_runs
├── api/schemas.py                 # RunSummary/RunDetail: source_run_id, replay_outcome, finding (true for a
│                                  #   succeeded, non-replay run — ui/app.py's headline cards read this together
│                                  #   with hard_evidence for Confirmed/Suspected, never the mode), replayable,
│                                  #   replay_blocked_reason (computed
│                                  #   server-side from the run AND its target's current permission/terms/
│                                  #   other-run-in-progress state, never from the run's own fields alone — seven
│                                  #   exact reason strings in total), replay_advisory (new, separate from
│                                  #   replay_blocked_reason — a replayable run can still carry one); RunDetail:
│                                  #   comparison (ReplayComparisonOut | None — NOT ComparisonOut, which already
│                                  #   names the 007 experiment significance shape, api/schemas.py:314 — including
│                                  #   multi_turn_caption, the pinned FR-041 string for a multi-message source);
│                                  #   BatchReplayResultOut (entries, counts, complete, stop_reason — including
│                                  #   "replay_failed" — not_replayed_source_ids),
│                                  #   BatchReplayEntryOut (incl. both *_hard_evidence fields); ConfigOut.replay
│                                  #   (batch cap, and per_replay_time_limit_s = max(adaptive time limit,
│                                  #   single-turn deadline) for the CI script's own timeout)
├── api/main.py                    # POST /api/runs/{run_id}/replay (**201**, a run is created, like POST
│                                  #   /api/runs today); POST /api/targets/{target_id}/replays (**200** for
│                                  #   every batch result — complete, incomplete, or zero entries alike,
│                                  #   not 201, since a batch creates N runs, not one
│                                  #   resource; a precondition refused before the batch starts keeps its own 4xx);
│                                  #   target_report filters out mode == "replay" before build_report/
│                                  #   recommendations_for
└── report/model.py                # untouched — the filter lives at the api/main.py call site (research D9)
ui/
├── api_client.py                  # replay_run(run_id) only — no batch_replay client; the UI has no batch
│                                  #   action (the spec asks only for a single-run
│                                  #   Replay button)
└── app.py                         # Replay button, outcome line, multi-turn caption and comparison all render
│                                  #   before `_render_finding`'s failure-step early return
│                                  #   (app.py:520-525 returns early for a run
│                                  #   whose send failed, so all of these must render ahead of that branch to
│                                  #   appear — the button disabled — for those runs too), keyed by render context
│                                  #   (the result card vs. an opened run — a fixed key
│                                  #   would collide when both render in one pass); run-list Mode/Source columns;
│                                  #   the side-by-side table; render_metrics (app.py:909-911) drives Confirmed/
│                                  #   Suspected from `run["finding"]` and `run["hard_evidence"]` together (two
│                                  #   server-computed values, no mode check of any kind in the UI)
scripts/
└── check_replay.py                # NEW — CI gate: --target-id, KESTREL_API_URL/KESTREL_API_TOKEN, exit 0/1/2/3
tests/
├── support.py                     # (extend) a tiny replay-eligible run/turn builder helper if needed
├── unit/test_store_migration_v10.py        # the v10 rebuild, per the per-version convention (012/FR-020 et al.)
├── unit/test_replay_eligibility.py         # check_replayable, list_replayable_runs ordering (012/FR-004, FR-005)
├── unit/test_replay_outcome.py             # compute_outcome's pure mapping, every branch (012/FR-013 to FR-015)
├── unit/test_replay_comparison.py          # build_comparison, including the terminal-turn derivation (012/FR-017)
├── unit/test_events_replay.py              # the new catalogue fields and events (012/FR-043, FR-044, FR-045)
├── integration/test_replay_run.py          # single-turn and adaptive replay end to end offline, outcomes,
│                                            #   verbatim resend, no attacker call, stop-at-first-success,
│                                            #   provenance copy (012/FR-001 to FR-023)
├── integration/test_replay_memory_isolation.py   # SpyExperienceStore sees 0 calls, across a replay and a batch
│                                                  #   (012/FR-025, FR-026, SC-003)
├── integration/test_replay_report_exclusion.py   # report findings/counts/recommendations unchanged (012/FR-027)
├── integration/test_replay_batch.py        # ordering, cap refusal, zero-replayable, per-outcome counts (FR-028
│                                            #   to FR-033)
├── integration/test_replay_api.py          # the two endpoints' shapes and error codes (012/FR-038 to FR-041)
├── unit/test_check_replay_script.py        # the CI script's exit codes and output, over a stubbed API (FR-034
│                                            #   to FR-037)
└── e2e/test_us012_replay.py                # one e2e against the HS-code target (012/FR-050-adjacent, SC-010)
specs/010-structured-logging/contracts/log-records.md   # the rows of contracts/log-records-delta.md merged in;
                                              #   the implementation PR carries a `spec-change:` note for this
                                              #   edit (the traceability gate requires it, tasks.md's PR-checklist
                                              #   line)
docs/roadmap.md, README.md, CLAUDE.md        # last task only, implementation PR: roadmap Done entry, 001–012
                                              #   status lines (README.md has two — the opening Status paragraph
                                              #   and the "What's next" section), a CLAUDE.md learned note (FR-050)
```

**Structure Decision**: the existing single package `src/kestrel/` + `ui/` + `scripts/`. One new module,
`replay.py`, beside `runs.py` (the same split feature 003 already made between `runs.py` and `attack/graph.py`); one
new function in `attack/graph.py` beside `run_adaptive`. Because `judge_node`/`send_node`/`evidence_node`/
`decide_node` are closures defined inside `run_adaptive` today, not independently callable, "sharing" them is a
mechanical refactor, not a reuse: each is lifted to a module-level function taking what it used to close over as
parameters, and both `run_adaptive` and `run_replay_adaptive` wire a thin closure to the shared function (research
D14) — proven behaviour-preserving by `run_adaptive`'s own existing tests passing unmodified afterward.
`attacker_node` and `record_node` differ in substance (FR-001/FR-002: a model call versus a list lookup; run-wide
versus per-turn provenance) and are written separately for the replay, beside `run_adaptive`'s own. No new
top-level package; the UI stays a thin client of the API (FR-042), with no batch action in it at all (only the CI
script calls the batch endpoint).

## Phase status

- Phase 0 (research): done — `research.md`.
- Phase 1 (design): done — `data-model.md`, `contracts/`, `quickstart.md`; Constitution Check re-evaluated after
  design: PASS (no new dependency, the Principle-V deviation is justified and recorded in Complexity Tracking and
  is visible on every affected run as `memory_written = "not attempted"`, no new report section, caps unchanged
  apart from the one new, configurable batch cap). The outcome rule (research D5) reads every replay turn's own
  result, never the run's one aggregate `verdict` (which could otherwise silently hide an early unresolved turn
  behind a later clean failure), and additionally requires a multi-message source's own winning turn to have
  itself failed under the judge; `replayable`/the blocked reason/the advisory are computed from the run **and
  its target's current permission/terms/in-progress state**, not the run alone, with every one of the seven
  reason strings pinned word for word (FR-004 to FR-006, FR-040); the batch endpoint always answers `200` (never
  `201`); a `finding` flag, together with `hard_evidence`, drives the UI's Confirmed/Suspected headline cards
  with no mode check; a single replay's own unexpected failure inside a batch closes that entry's row and raises
  a named `ReplayFailed`, giving the batch loop a defined, non-500 shape to catch (`stop_reason:
  "replay_failed"`), with each batch entry running inside its own `events.run_scope()`.
- Phase 2 (tasks): `/speckit-tasks` → `tasks.md`.
